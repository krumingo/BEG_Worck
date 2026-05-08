"""
Tests for Media ACL Security (Stage 1.3)

Tests verify:
1. Cross-org access is blocked (user from org A cannot access media from org B)
2. Role-based access within same org:
   - Admin: full access to all media in org
   - Owner: full access to all media in org
   - Technician: only own media or media linked to their contexts
3. DELETE endpoint respects ACL
4. File serving respects ACL
"""
import pytest
import requests
import uuid
import os

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_TECH_PASSWORD, VALID_STRONG_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
API_URL = f"{BASE_URL}/api"


class TestMediaACLCrossOrg:
    """Test cross-organization access is blocked"""
    
    @pytest.fixture(scope="class")
    def org_a_admin(self):
        """Admin from org A (existing test org)"""
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Admin user not available")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def org_b_user(self):
        """Create a user in a different org (org B)"""
        # Create new org via signup
        unique_email = f"orgb_test_{uuid.uuid4().hex[:8]}@example.com"
        resp = requests.post(f"{API_URL}/billing/signup", json={
            "org_name": f"Test Org B {uuid.uuid4().hex[:6]}",
            "owner_name": "Org B Owner",
            "owner_email": unique_email,
            "password": VALID_STRONG_PASSWORD,
        })
        if resp.status_code != 200:
            pytest.skip(f"Could not create org B: {resp.text}")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def org_a_media_id(self, org_a_admin):
        """Upload media in org A and return its ID"""
        token = org_a_admin["token"]
        
        # Create a small test image
        import io
        from PIL import Image
        
        img = Image.new('RGB', (100, 100), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("test_acl.jpg", img_bytes, "image/jpeg")}
        resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Could not upload test media: {resp.text}")
        
        return resp.json()["id"]
    
    def test_cross_org_get_media_returns_404(self, org_a_media_id, org_b_user):
        """User from org B should get 404 when trying to access org A media"""
        token = org_b_user["token"]
        
        resp = requests.get(
            f"{API_URL}/media/{org_a_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Should return 404 (not 403) to avoid revealing existence
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    
    def test_cross_org_list_media_excludes_other_org(self, org_a_media_id, org_b_user):
        """User from org B should not see org A media in list"""
        token = org_b_user["token"]
        
        resp = requests.get(
            f"{API_URL}/media",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 200
        media_ids = [m["id"] for m in resp.json()]
        assert org_a_media_id not in media_ids, "Org A media should not appear in org B list"
    
    def test_cross_org_delete_returns_404(self, org_a_media_id, org_b_user):
        """User from org B should get 404 when trying to delete org A media"""
        token = org_b_user["token"]
        
        resp = requests.delete(
            f"{API_URL}/media/{org_a_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 404


class TestMediaACLWithinOrg:
    """Test role-based access within same organization"""
    
    @pytest.fixture(scope="class")
    def admin_auth(self):
        """Get admin authentication"""
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Admin user not available")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def tech_auth(self):
        """Get technician authentication"""
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "tech@begwork.com",
            "password": VALID_TECH_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Tech user not available")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def admin_media_id(self, admin_auth):
        """Upload media as admin (no context)"""
        token = admin_auth["token"]
        
        import io
        from PIL import Image
        
        img = Image.new('RGB', (100, 100), color='blue')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("admin_media.jpg", img_bytes, "image/jpeg")}
        resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Could not upload admin media: {resp.text}")
        
        return resp.json()["id"]
    
    @pytest.fixture(scope="class")
    def tech_media_id(self, tech_auth):
        """Upload media as technician (no context)"""
        token = tech_auth["token"]
        
        import io
        from PIL import Image
        
        img = Image.new('RGB', (100, 100), color='green')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("tech_media.jpg", img_bytes, "image/jpeg")}
        resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Could not upload tech media: {resp.text}")
        
        return resp.json()["id"]
    
    def test_admin_can_access_all_org_media(self, admin_auth, tech_media_id):
        """Admin should be able to access any media in the org"""
        token = admin_auth["token"]
        
        resp = requests.get(
            f"{API_URL}/media/{tech_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 200
    
    def test_tech_can_access_own_media(self, tech_auth, tech_media_id):
        """Technician should access their own media"""
        token = tech_auth["token"]
        
        resp = requests.get(
            f"{API_URL}/media/{tech_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 200
    
    def test_tech_cannot_access_unlinked_admin_media(self, tech_auth, admin_media_id):
        """Technician should NOT access admin's unlinked media"""
        token = tech_auth["token"]
        
        resp = requests.get(
            f"{API_URL}/media/{admin_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Should be 403 (same org but no access)
        assert resp.status_code == 403
    
    def test_tech_cannot_delete_admin_media(self, tech_auth, admin_media_id):
        """Technician should NOT be able to delete admin's media"""
        token = tech_auth["token"]
        
        resp = requests.delete(
            f"{API_URL}/media/{admin_media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 403
    
    def test_admin_can_delete_any_org_media(self, admin_auth, tech_auth):
        """Admin should be able to delete any media in the org"""
        # First, create media as tech
        tech_token = tech_auth["token"]
        
        import io
        from PIL import Image
        
        img = Image.new('RGB', (50, 50), color='yellow')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("to_delete.jpg", img_bytes, "image/jpeg")}
        upload_resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {tech_token}"},
            files=files
        )
        
        if upload_resp.status_code != 200:
            pytest.skip("Could not upload test media")
        
        media_id = upload_resp.json()["id"]
        
        # Now delete as admin
        admin_token = admin_auth["token"]
        delete_resp = requests.delete(
            f"{API_URL}/media/{media_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert delete_resp.status_code == 200
        assert delete_resp.json()["ok"] == True


class TestMediaFileServing:
    """Test that file serving endpoint respects ACL"""
    
    @pytest.fixture(scope="class")
    def admin_auth(self):
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Admin user not available")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def org_b_user(self):
        """Create a user in a different org"""
        unique_email = f"orgb_file_{uuid.uuid4().hex[:8]}@example.com"
        resp = requests.post(f"{API_URL}/billing/signup", json={
            "org_name": f"Test Org File {uuid.uuid4().hex[:6]}",
            "owner_name": "Org File Owner",
            "owner_email": unique_email,
            "password": VALID_STRONG_PASSWORD,
        })
        if resp.status_code != 200:
            pytest.skip(f"Could not create org: {resp.text}")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def uploaded_file_info(self, admin_auth):
        """Upload a file and get its info"""
        token = admin_auth["token"]
        
        import io
        from PIL import Image
        
        img = Image.new('RGB', (100, 100), color='purple')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("file_test.jpg", img_bytes, "image/jpeg")}
        resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Could not upload file: {resp.text}")
        
        data = resp.json()
        return {
            "id": data["id"],
            "url": data["url"],
            "filename": data["url"].split("/")[-1]  # Extract filename from URL
        }
    
    def test_owner_can_download_file(self, admin_auth, uploaded_file_info):
        """Owner should be able to download the file"""
        token = admin_auth["token"]
        
        resp = requests.get(
            f"{BASE_URL}{uploaded_file_info['url']}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert resp.status_code == 200
        assert len(resp.content) > 0
    
    def test_cross_org_cannot_download_file(self, uploaded_file_info, org_b_user):
        """User from different org should not download the file"""
        token = org_b_user["token"]
        
        resp = requests.get(
            f"{BASE_URL}{uploaded_file_info['url']}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Should return 404 (media not found for this org)
        assert resp.status_code == 404
    
    def test_unauthenticated_cannot_download(self, uploaded_file_info):
        """Unauthenticated request should be blocked"""
        resp = requests.get(f"{BASE_URL}{uploaded_file_info['url']}")
        
        # Should return 403 (no auth)
        assert resp.status_code == 403


class TestMediaLinkACL:
    """Test that media linking respects context ACL"""
    
    @pytest.fixture(scope="class")
    def admin_auth(self):
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Admin user not available")
        return resp.json()
    
    @pytest.fixture(scope="class")
    def tech_auth(self):
        resp = requests.post(f"{API_URL}/auth/login", json={
            "email": "tech@begwork.com",
            "password": VALID_TECH_PASSWORD
        })
        if resp.status_code != 200:
            pytest.skip("Tech user not available")
        return resp.json()
    
    def test_tech_cannot_link_to_unknown_context(self, tech_auth):
        """Technician cannot link media to a context they don't have access to"""
        token = tech_auth["token"]
        
        # First upload media
        import io
        from PIL import Image
        
        img = Image.new('RGB', (50, 50), color='cyan')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("link_test.jpg", img_bytes, "image/jpeg")}
        upload_resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if upload_resp.status_code != 200:
            pytest.skip("Could not upload test media")
        
        media_id = upload_resp.json()["id"]
        
        # Try to link to a non-existent project
        link_resp = requests.post(
            f"{API_URL}/media/link",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "media_id": media_id,
                "context_type": "project",
                "context_id": "nonexistent-project-12345"
            }
        )
        
        # Should fail with 403 (no access to context)
        assert link_resp.status_code == 403
    
    def test_admin_can_link_to_any_org_context(self, admin_auth):
        """Admin can link media to any context in their org"""
        token = admin_auth["token"]
        admin_user = admin_auth["user"]
        
        # Upload media
        import io
        from PIL import Image
        
        img = Image.new('RGB', (50, 50), color='magenta')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        files = {"file": ("admin_link.jpg", img_bytes, "image/jpeg")}
        upload_resp = requests.post(
            f"{API_URL}/media/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )
        
        if upload_resp.status_code != 200:
            pytest.skip("Could not upload test media")
        
        media_id = upload_resp.json()["id"]
        
        # Link to own profile (always valid for admin)
        link_resp = requests.post(
            f"{API_URL}/media/link",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "media_id": media_id,
                "context_type": "profile",
                "context_id": admin_user["id"]
            }
        )
        
        assert link_resp.status_code == 200
        assert link_resp.json()["linked"] == True
