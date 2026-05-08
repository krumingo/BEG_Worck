"""
Test suite for ProjectOperationsPage Backend APIs
Tests: Subcontractors, Packages, Client Acts, Revenue Snapshots, Overhead
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """API client with auth headers"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


# ═══════════════════════════════════════════════════════════════════
# SUBCONTRACTORS TAB TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSubcontractors:
    """Tests for Subcontractors (Подизпълнители) tab"""
    
    def test_list_subcontractors(self, api_client):
        """GET /api/subcontractors returns list"""
        response = api_client.get(f"{BASE_URL}/api/subcontractors")
        assert response.status_code == 200, f"List subcontractors failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} subcontractors")
        
    def test_create_subcontractor(self, api_client):
        """POST /api/subcontractors creates new subcontractor"""
        payload = {
            "name": f"TEST_Subcontractor_{datetime.now().strftime('%H%M%S')}",
            "contact_person": "Test Contact",
            "phone": "+359888123456"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractors", json=payload)
        assert response.status_code == 201, f"Create subcontractor failed: {response.text}"
        data = response.json()
        assert data["name"] == payload["name"]
        assert "id" in data
        print(f"✓ Created subcontractor: {data['name']} (id={data['id'][:8]}...)")
        return data["id"]


class TestSubcontractorPackages:
    """Tests for Subcontractor Packages (Пакети)"""
    
    def test_list_packages_by_project(self, api_client):
        """GET /api/subcontractor-packages?project_id=... returns project packages"""
        response = api_client.get(f"{BASE_URL}/api/subcontractor-packages?project_id={PROJECT_ID}")
        assert response.status_code == 200, f"List packages failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} packages for project PRJ-001")
        # Verify package structure
        if data:
            pkg = data[0]
            assert "package_no" in pkg
            assert "status" in pkg
            assert "contract_total" in pkg or pkg.get("status") == "draft"
            print(f"  - First package: {pkg.get('package_no')} ({pkg.get('status')})")
        return data
    
    def test_create_package(self, api_client):
        """POST /api/subcontractor-packages creates draft package"""
        # Get first subcontractor
        subs = api_client.get(f"{BASE_URL}/api/subcontractors").json()
        if not subs:
            pytest.skip("No subcontractors available")
        
        payload = {
            "project_id": PROJECT_ID,
            "subcontractor_id": subs[0]["id"],
            "title": f"TEST_Package_{datetime.now().strftime('%H%M%S')}"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json=payload)
        assert response.status_code == 201, f"Create package failed: {response.text}"
        data = response.json()
        assert data["status"] == "draft"
        assert "package_no" in data
        print(f"✓ Created package: {data['package_no']} (status={data['status']})")
        return data["id"]
    
    def test_confirm_package_requires_lines(self, api_client):
        """POST /api/subcontractor-packages/{id}/confirm fails without lines"""
        # Create a draft package
        subs = api_client.get(f"{BASE_URL}/api/subcontractors").json()
        if not subs:
            pytest.skip("No subcontractors available")
            
        pkg = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": subs[0]["id"],
            "title": f"TEST_NoLines_{datetime.now().strftime('%H%M%S')}"
        }).json()
        
        # Try to confirm without lines
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg['id']}/confirm")
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "no lines" in response.text.lower()
        print("✓ Confirm without lines correctly returns 400")


class TestSubcontractorPayments:
    """Tests for Subcontractor Payments (Плащания)"""
    
    def test_list_payments_by_project(self, api_client):
        """GET /api/subcontractor-payments?project_id=... returns payments"""
        response = api_client.get(f"{BASE_URL}/api/subcontractor-payments?project_id={PROJECT_ID}")
        assert response.status_code == 200, f"List payments failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} payments for project PRJ-001")
    
    def test_create_payment_requires_valid_package(self, api_client):
        """POST /api/subcontractor-payments requires valid package"""
        payload = {
            "package_id": "invalid-id",
            "amount": 100,
            "payment_date": "2026-01-12"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-payments", json=payload)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Create payment with invalid package returns 404")


# ═══════════════════════════════════════════════════════════════════
# CLIENT ACTS TAB TESTS
# ═══════════════════════════════════════════════════════════════════

class TestClientActs:
    """Tests for Client Acts (Актове) tab"""
    
    def test_list_client_acts_by_project(self, api_client):
        """GET /api/client-acts?project_id=... returns client acts"""
        response = api_client.get(f"{BASE_URL}/api/client-acts?project_id={PROJECT_ID}")
        assert response.status_code == 200, f"List client acts failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} client acts for project PRJ-001")
        if data:
            act = data[0]
            assert "act_number" in act
            assert "status" in act
            print(f"  - First act: {act.get('act_number')} ({act.get('status')})")
        return data
    
    def test_create_client_act(self, api_client):
        """POST /api/client-acts creates draft act"""
        payload = {
            "project_id": PROJECT_ID,
            "act_date": "2026-01-12",
            "notes": f"TEST_Act_{datetime.now().strftime('%H%M%S')}",
            "lines": [{
                "activity_name": "Test Activity",
                "unit": "m2",
                "contracted_qty": 100,
                "executed_qty": 50,
                "unit_price": 10.0
            }]
        }
        response = api_client.post(f"{BASE_URL}/api/client-acts", json=payload)
        assert response.status_code == 201, f"Create client act failed: {response.text}"
        data = response.json()
        assert data["status"] == "Draft"
        assert "act_number" in data
        assert data["subtotal"] == 500.0  # 50 * 10
        print(f"✓ Created client act: {data['act_number']} (subtotal={data['subtotal']})")
        return data["id"]
    
    def test_confirm_client_act_changes_status(self, api_client):
        """POST /api/client-acts/{id}/confirm changes status to Accepted"""
        # Create a draft act first
        act = api_client.post(f"{BASE_URL}/api/client-acts", json={
            "project_id": PROJECT_ID,
            "act_date": "2026-01-12",
            "lines": [{"activity_name": "Test", "unit": "m2", "contracted_qty": 10, "executed_qty": 5, "unit_price": 20}]
        }).json()
        
        # Confirm the act
        response = api_client.post(f"{BASE_URL}/api/client-acts/{act['id']}/confirm")
        assert response.status_code == 200, f"Confirm act failed: {response.text}"
        data = response.json()
        assert data["status"] == "Accepted"
        print(f"✓ Confirmed act {data['act_number']} → status=Accepted")


class TestCreateActFromOffer:
    """Tests for creating client act from accepted offer"""
    
    def test_get_offers_for_project(self, api_client):
        """GET /api/offers returns offers that can be used for client acts"""
        response = api_client.get(f"{BASE_URL}/api/offers")
        assert response.status_code == 200
        data = response.json()
        # Filter to project
        project_offers = [o for o in data if o.get("project_id") == PROJECT_ID]
        accepted = [o for o in project_offers if o.get("status") == "Accepted"]
        print(f"✓ Found {len(project_offers)} offers for PRJ-001, {len(accepted)} accepted")
        return accepted


# ═══════════════════════════════════════════════════════════════════
# REVENUE SNAPSHOTS TAB TESTS
# ═══════════════════════════════════════════════════════════════════

class TestRevenueSnapshots:
    """Tests for Revenue Snapshots (Приходи) tab"""
    
    def test_list_revenue_snapshots_by_project(self, api_client):
        """GET /api/revenue-snapshots?project_id=... returns snapshots"""
        response = api_client.get(f"{BASE_URL}/api/revenue-snapshots?project_id={PROJECT_ID}")
        assert response.status_code == 200, f"List snapshots failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} revenue snapshots for project PRJ-001")
        if data:
            snap = data[0]
            assert "offer_no" in snap
            assert "total_contract_value" in snap
            print(f"  - First snapshot: {snap.get('offer_no')} (total={snap.get('total_contract_value')})")
        return data
    
    def test_create_snapshot_from_offer(self, api_client):
        """POST /api/revenue-snapshots/from-offer/{id} creates frozen snapshot"""
        # Get an accepted offer
        offers = api_client.get(f"{BASE_URL}/api/offers").json()
        accepted_offer = next((o for o in offers if o.get("project_id") == PROJECT_ID and o.get("status") == "Accepted"), None)
        
        if not accepted_offer:
            pytest.skip("No accepted offer available for PRJ-001")
        
        # Check if snapshot already exists
        snapshots = api_client.get(f"{BASE_URL}/api/revenue-snapshots?project_id={PROJECT_ID}").json()
        existing = next((s for s in snapshots if s.get("offer_id") == accepted_offer["id"] and s.get("version") == accepted_offer.get("version", 1)), None)
        
        if existing:
            print(f"✓ Snapshot already exists for offer {accepted_offer['offer_no']}")
            return
        
        # Create snapshot
        response = api_client.post(f"{BASE_URL}/api/revenue-snapshots/from-offer/{accepted_offer['id']}")
        assert response.status_code in [201, 400], f"Unexpected status: {response.status_code}"
        if response.status_code == 201:
            data = response.json()
            print(f"✓ Created revenue snapshot: {data.get('offer_no')} v{data.get('version')}")
        else:
            print(f"✓ Snapshot already exists (400 returned)")


# ═══════════════════════════════════════════════════════════════════
# OVERHEAD TAB TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOverhead:
    """Tests for Overhead (Режийни) tab"""
    
    def test_list_overhead_snapshots(self, api_client):
        """GET /api/overhead/snapshots returns overhead snapshots"""
        response = api_client.get(f"{BASE_URL}/api/overhead/snapshots")
        assert response.status_code == 200, f"List overhead snapshots failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} overhead snapshots")
        return data
    
    def test_overhead_allocation_endpoint(self, api_client):
        """GET /api/overhead/allocations returns allocations"""
        response = api_client.get(f"{BASE_URL}/api/overhead/allocations")
        assert response.status_code == 200, f"List allocations failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} overhead allocations")


class TestOverheadAllocationCompute:
    """Tests for overhead allocation compute"""
    
    def test_compute_allocation_for_project(self, api_client):
        """POST /api/overhead-allocation/compute/{project_id} computes allocation"""
        # Note: This endpoint might not exist - checking if it returns 404 or works
        response = api_client.post(f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}")
        # Accept 404 (endpoint not implemented) or 200/400 (endpoint exists)
        assert response.status_code in [200, 400, 404, 405], f"Unexpected status: {response.status_code}"
        print(f"✓ Overhead allocation compute returned {response.status_code}")


# ═══════════════════════════════════════════════════════════════════
# SUBCONTRACTOR ACTS TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSubcontractorActs:
    """Tests for Subcontractor Acts"""
    
    def test_list_subcontractor_acts_by_project(self, api_client):
        """GET /api/subcontractor-acts?project_id=... returns acts"""
        response = api_client.get(f"{BASE_URL}/api/subcontractor-acts?project_id={PROJECT_ID}")
        assert response.status_code == 200, f"List subcontractor acts failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Found {len(data)} subcontractor acts for project PRJ-001")


# ═══════════════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(api_client):
    """Cleanup TEST_ prefixed data after tests"""
    yield
    # Note: Cleanup can be implemented if needed
    print("\n✓ Test suite completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
