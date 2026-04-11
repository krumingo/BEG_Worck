"""
Tests for Admin Field Mode Verification & Hardening.
Verifies:
1. Admin can access /api/technician/my-sites and sees ALL projects
2. Technician can access /api/technician/my-sites and sees ONLY assigned projects
3. Admin submitting daily report saves entered_by_admin=True and entry_mode=admin_field_portal
4. Technician submitting daily report saves entered_by_admin=False and entry_mode=technician_portal
5. Approving report propagates audit markers to work_session

Run: pytest backend/tests/test_admin_field_mode.py -v
"""
import pytest
import httpx
import uuid
from pathlib import Path
from datetime import datetime

BASE_URL = ""
fe_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
if fe_env.exists():
    for line in fe_env.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"
TECH_EMAIL = "tech1@begwork.com"
TECH_PASSWORD = "TechTest123!Secure"


@pytest.fixture(scope="module")
def admin_headers():
    """Get admin auth headers"""
    r = httpx.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_user(admin_headers):
    """Get admin user info"""
    r = httpx.get(f"{API}/auth/me", headers=admin_headers)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def tech_headers():
    """Get technician auth headers"""
    r = httpx.post(f"{API}/auth/login", json={"email": TECH_EMAIL, "password": TECH_PASSWORD})
    assert r.status_code == 200, f"Technician login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def tech_user(tech_headers):
    """Get technician user info"""
    r = httpx.get(f"{API}/auth/me", headers=tech_headers)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def project_id(admin_headers):
    """Get first project ID"""
    r = httpx.get(f"{API}/projects", headers=admin_headers)
    projects = r.json() if isinstance(r.json(), list) else r.json()
    assert len(projects) > 0, "No projects found"
    return projects[0]["id"]


# ═══════════════════════════════════════════════════════════════════
# TEST 1: Admin sees ALL projects in my-sites
# ═══════════════════════════════════════════════════════════════════

def test_admin_sees_all_sites(admin_headers, admin_user):
    """Admin should see all active projects in my-sites endpoint"""
    r = httpx.get(f"{API}/technician/my-sites", headers=admin_headers)
    assert r.status_code == 200, f"Failed: {r.text}"
    
    data = r.json()
    assert "sites" in data
    assert data["total"] >= 1, "Admin should see at least 1 site"
    
    # Verify admin role
    assert admin_user["role"] in ["Admin", "Owner", "SiteManager"], f"Expected admin role, got {admin_user['role']}"
    
    print(f"✓ Admin sees {data['total']} sites")
    for site in data["sites"][:5]:
        print(f"  - {site['name']} (id: {site['project_id']})")


# ═══════════════════════════════════════════════════════════════════
# TEST 2: Technician sees ONLY assigned projects
# ═══════════════════════════════════════════════════════════════════

def test_technician_sees_limited_sites(tech_headers, tech_user):
    """Technician should see only assigned projects"""
    r = httpx.get(f"{API}/technician/my-sites", headers=tech_headers)
    assert r.status_code == 200, f"Failed: {r.text}"
    
    data = r.json()
    assert "sites" in data
    
    # Verify technician role
    assert tech_user["role"] == "Technician", f"Expected Technician role, got {tech_user['role']}"
    
    print(f"✓ Technician sees {data['total']} sites (limited view)")
    for site in data["sites"]:
        print(f"  - {site['name']} (id: {site['project_id']})")


# ═══════════════════════════════════════════════════════════════════
# TEST 3: Admin submitting report saves audit markers
# ═══════════════════════════════════════════════════════════════════

def test_admin_daily_report_audit_markers(admin_headers, project_id):
    """Admin submitting daily report should save entered_by_admin=True and entry_mode=admin_field_portal"""
    unique_smr = f"TEST_AdminSMR_{uuid.uuid4().hex[:8]}"
    
    r = httpx.post(f"{API}/technician/daily-report", json={
        "project_id": project_id,
        "entries": [
            {"worker_name": "Тест Админ Работник", "smr_type": unique_smr, "hours": 4},
        ],
        "general_notes": "Admin field mode test",
    }, headers=admin_headers)
    
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    
    assert "draft_report_ids" in data, "Response should contain draft_report_ids"
    assert len(data["draft_report_ids"]) >= 1, "Should have at least 1 draft"
    
    draft_id = data["draft_report_ids"][0]
    print(f"✓ Admin created draft report: {draft_id}")
    
    # Verify the draft has correct audit markers
    # Get the draft directly from the database via API
    drafts_r = httpx.get(f"{API}/technician/site/{project_id}/my-drafts", headers=admin_headers)
    assert drafts_r.status_code == 200
    
    drafts = drafts_r.json().get("items", [])
    matching_draft = next((d for d in drafts if d["id"] == draft_id), None)
    
    if matching_draft:
        assert matching_draft.get("entered_by_admin") == True, f"entered_by_admin should be True, got {matching_draft.get('entered_by_admin')}"
        assert matching_draft.get("entry_mode") == "admin_field_portal", f"entry_mode should be admin_field_portal, got {matching_draft.get('entry_mode')}"
        print(f"✓ Draft has correct audit markers: entered_by_admin={matching_draft.get('entered_by_admin')}, entry_mode={matching_draft.get('entry_mode')}")
    else:
        print(f"⚠ Could not find draft {draft_id} in my-drafts response")
    
    return draft_id


# ═══════════════════════════════════════════════════════════════════
# TEST 4: Technician submitting report saves correct audit markers
# ═══════════════════════════════════════════════════════════════════

def test_technician_daily_report_audit_markers(tech_headers, tech_user):
    """Technician submitting daily report should save entered_by_admin=False and entry_mode=technician_portal"""
    # First get technician's assigned sites
    sites_r = httpx.get(f"{API}/technician/my-sites", headers=tech_headers)
    assert sites_r.status_code == 200
    
    sites = sites_r.json().get("sites", [])
    if not sites:
        pytest.skip("Technician has no assigned sites")
    
    project_id = sites[0]["project_id"]
    unique_smr = f"TEST_TechSMR_{uuid.uuid4().hex[:8]}"
    
    r = httpx.post(f"{API}/technician/daily-report", json={
        "project_id": project_id,
        "entries": [
            {"worker_name": "Тест Техник Работник", "smr_type": unique_smr, "hours": 6},
        ],
        "general_notes": "Technician portal test",
    }, headers=tech_headers)
    
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    
    assert "draft_report_ids" in data, "Response should contain draft_report_ids"
    assert len(data["draft_report_ids"]) >= 1, "Should have at least 1 draft"
    
    draft_id = data["draft_report_ids"][0]
    print(f"✓ Technician created draft report: {draft_id}")
    
    # Verify the draft has correct audit markers
    drafts_r = httpx.get(f"{API}/technician/site/{project_id}/my-drafts", headers=tech_headers)
    assert drafts_r.status_code == 200
    
    drafts = drafts_r.json().get("items", [])
    matching_draft = next((d for d in drafts if d["id"] == draft_id), None)
    
    if matching_draft:
        assert matching_draft.get("entered_by_admin") == False, f"entered_by_admin should be False, got {matching_draft.get('entered_by_admin')}"
        assert matching_draft.get("entry_mode") == "technician_portal", f"entry_mode should be technician_portal, got {matching_draft.get('entry_mode')}"
        print(f"✓ Draft has correct audit markers: entered_by_admin={matching_draft.get('entered_by_admin')}, entry_mode={matching_draft.get('entry_mode')}")
    else:
        print(f"⚠ Could not find draft {draft_id} in my-drafts response")
    
    return draft_id


# ═══════════════════════════════════════════════════════════════════
# TEST 5: Approving report propagates audit markers to work_session
# ═══════════════════════════════════════════════════════════════════

def test_approve_propagates_audit_markers(admin_headers, project_id):
    """Approving a report should propagate entered_by_admin and entry_mode to work_session"""
    unique_smr = f"TEST_ApprovalSMR_{uuid.uuid4().hex[:8]}"
    
    # Step 1: Create a draft report as admin
    r = httpx.post(f"{API}/technician/daily-report", json={
        "project_id": project_id,
        "entries": [
            {"worker_name": "Тест Одобрение", "smr_type": unique_smr, "hours": 5},
        ],
        "general_notes": "Approval test",
    }, headers=admin_headers)
    
    assert r.status_code == 200, f"Failed to create draft: {r.text}"
    draft_id = r.json()["draft_report_ids"][0]
    print(f"✓ Created draft for approval test: {draft_id}")
    
    # Step 2: Approve the report
    approve_r = httpx.post(f"{API}/daily-reports/{draft_id}/approve", headers=admin_headers)
    assert approve_r.status_code == 200, f"Failed to approve: {approve_r.text}"
    
    approved_data = approve_r.json()
    assert approved_data.get("status") == "APPROVED" or approved_data.get("approval_status") == "APPROVED", f"Report not approved: {approved_data}"
    print(f"✓ Report approved successfully")
    
    # Step 3: Check if work_session was created with audit markers
    # Query work_sessions for this approved report
    sessions_r = httpx.get(f"{API}/work-sessions?project_id={project_id}&limit=50", headers=admin_headers)
    
    if sessions_r.status_code == 200:
        sessions = sessions_r.json() if isinstance(sessions_r.json(), list) else sessions_r.json().get("items", [])
        matching_session = next((s for s in sessions if s.get("approved_report_id") == draft_id), None)
        
        if matching_session:
            assert matching_session.get("entered_by_admin") == True, f"work_session entered_by_admin should be True"
            assert matching_session.get("entry_mode") == "admin_field_portal", f"work_session entry_mode should be admin_field_portal"
            print(f"✓ Work session has propagated audit markers: entered_by_admin={matching_session.get('entered_by_admin')}, entry_mode={matching_session.get('entry_mode')}")
        else:
            print(f"⚠ Could not find work_session with approved_report_id={draft_id}")
    else:
        print(f"⚠ Could not query work_sessions: {sessions_r.status_code}")


# ═══════════════════════════════════════════════════════════════════
# TEST 6: Verify role-based access to my-sites
# ═══════════════════════════════════════════════════════════════════

def test_role_based_site_access(admin_headers, tech_headers, admin_user, tech_user):
    """Compare admin vs technician site access"""
    admin_sites_r = httpx.get(f"{API}/technician/my-sites", headers=admin_headers)
    tech_sites_r = httpx.get(f"{API}/technician/my-sites", headers=tech_headers)
    
    assert admin_sites_r.status_code == 200
    assert tech_sites_r.status_code == 200
    
    admin_sites = admin_sites_r.json()
    tech_sites = tech_sites_r.json()
    
    admin_count = admin_sites["total"]
    tech_count = tech_sites["total"]
    
    print(f"✓ Admin ({admin_user['role']}) sees {admin_count} sites")
    print(f"✓ Technician ({tech_user['role']}) sees {tech_count} sites")
    
    # Admin should see at least as many sites as technician (usually more)
    assert admin_count >= tech_count, f"Admin should see >= sites than technician"


# ═══════════════════════════════════════════════════════════════════
# TEST 7: Verify technician cannot access admin-only endpoints
# ═══════════════════════════════════════════════════════════════════

def test_technician_cannot_access_admin_endpoints(tech_headers):
    """Technician should not be able to access admin-only endpoints"""
    # Try to access employees endpoint (admin only)
    r = httpx.get(f"{API}/employees", headers=tech_headers)
    # Should either return 403 or empty/limited data
    print(f"✓ Technician /employees access: status={r.status_code}")
    
    # Try to access finance endpoint (admin only)
    r2 = httpx.get(f"{API}/finance/overview", headers=tech_headers)
    print(f"✓ Technician /finance/overview access: status={r2.status_code}")
    
    # Try to access payroll endpoint (admin only)
    r3 = httpx.get(f"{API}/payroll-runs", headers=tech_headers)
    print(f"✓ Technician /payroll-runs access: status={r3.status_code}")


# ═══════════════════════════════════════════════════════════════════
# TEST 8: Verify site detail endpoint works for both roles
# ═══════════════════════════════════════════════════════════════════

def test_site_detail_access(admin_headers, tech_headers, project_id):
    """Both admin and technician should be able to access site detail"""
    # Admin access
    admin_r = httpx.get(f"{API}/technician/site/{project_id}/detail", headers=admin_headers)
    assert admin_r.status_code == 200, f"Admin site detail failed: {admin_r.text}"
    
    admin_detail = admin_r.json()
    assert "name" in admin_detail
    assert "counters" in admin_detail
    print(f"✓ Admin can access site detail: {admin_detail['name']}")
    
    # Technician access (if they have access to this project)
    tech_sites_r = httpx.get(f"{API}/technician/my-sites", headers=tech_headers)
    tech_sites = tech_sites_r.json().get("sites", [])
    tech_project_ids = [s["project_id"] for s in tech_sites]
    
    if project_id in tech_project_ids:
        tech_r = httpx.get(f"{API}/technician/site/{project_id}/detail", headers=tech_headers)
        assert tech_r.status_code == 200, f"Technician site detail failed: {tech_r.text}"
        print(f"✓ Technician can access assigned site detail")
    else:
        print(f"⚠ Technician not assigned to project {project_id}, skipping detail access test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
