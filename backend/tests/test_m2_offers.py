"""
from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_TECH_PASSWORD
M2 Offers/BOQ API Tests
Tests offer CRUD, BOQ lines, versioning, status transitions, totals computation, and activity catalog

Endpoints tested:
- POST /api/offers - Create offer with lines
- GET /api/offers - List offers with filters
- GET /api/offers/{id} - Get single offer
- PUT /api/offers/{id} - Update draft offer
- PUT /api/offers/{id}/lines - Update BOQ lines
- POST /api/offers/{id}/send - Change to Sent status
- POST /api/offers/{id}/accept - Accept offer (Admin/Owner only)
- POST /api/offers/{id}/reject - Reject offer (Admin/Owner only)
- POST /api/offers/{id}/new-version - Clone offer with incremented version
- DELETE /api/offers/{id} - Delete offer
- GET /api/activity-catalog - List activities
- POST /api/activity-catalog - Create activity
- PUT /api/activity-catalog/{id} - Update activity
- DELETE /api/activity-catalog/{id} - Delete activity
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD
TECH_EMAIL = "tech2@begwork.com"
TECH_PASSWORD = VALID_TECH_PASSWORD

@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]

@pytest.fixture(scope="module")
def admin_headers(admin_token):
    """Admin auth headers"""
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="module")
def tech_token():
    """Get technician auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TECH_EMAIL,
        "password": TECH_PASSWORD
    })
    if response.status_code != 200:
        pytest.skip("Technician user not available")
    return response.json()["token"]

@pytest.fixture(scope="module")
def tech_headers(tech_token):
    """Technician auth headers"""
    return {"Authorization": f"Bearer {tech_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="module")
def test_project_id(admin_headers):
    """Get or create a test project for offers"""
    # First check for existing active project
    response = requests.get(f"{BASE_URL}/api/projects", headers=admin_headers)
    assert response.status_code == 200
    projects = response.json()
    
    # Use first active project or any project
    for p in projects:
        if p["status"] == "Active":
            return p["id"]
    
    if projects:
        return projects[0]["id"]
    
    # Create new project if none exist
    unique_code = f"TEST-OFFER-{uuid.uuid4().hex[:6].upper()}"
    response = requests.post(f"{BASE_URL}/api/projects", headers=admin_headers, json={
        "code": unique_code,
        "name": "Test Project for Offers",
        "status": "Active",
        "type": "Billable"
    })
    assert response.status_code == 201
    return response.json()["id"]


class TestOfferCRUD:
    """Test Offer CRUD operations"""
    
    created_offer_id = None
    
    def test_create_offer_with_lines(self, admin_headers, test_project_id):
        """POST /api/offers - Create offer with BOQ lines and verify totals"""
        payload = {
            "project_id": test_project_id,
            "title": "TEST_Offer_AutoTest",
            "currency": "EUR",
            "vat_percent": 20.0,
            "notes": "Test offer created by automated tests",
            "lines": [
                {
                    "activity_code": "LINE-001",
                    "activity_name": "Test Activity 1",
                    "unit": "m2",
                    "qty": 10,
                    "material_unit_cost": 100,
                    "labor_unit_cost": 50,
                    "labor_hours_per_unit": 2,
                    "note": "First test line",
                    "sort_order": 0
                },
                {
                    "activity_code": "LINE-002",
                    "activity_name": "Test Activity 2",
                    "unit": "pcs",
                    "qty": 5,
                    "material_unit_cost": 200,
                    "labor_unit_cost": 80,
                    "labor_hours_per_unit": 1,
                    "note": "Second test line",
                    "sort_order": 1
                }
            ]
        }
        
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json=payload)
        assert response.status_code == 201, f"Create offer failed: {response.text}"
        
        offer = response.json()
        TestOfferCRUD.created_offer_id = offer["id"]
        
        # Verify basic fields
        assert offer["title"] == "TEST_Offer_AutoTest"
        assert offer["status"] == "Draft"
        assert offer["version"] == 1
        assert offer["currency"] == "EUR"
        assert offer["vat_percent"] == 20.0
        assert offer["project_id"] == test_project_id
        assert offer["offer_no"].startswith("OFF-")
        
        # Verify lines count
        assert len(offer["lines"]) == 2
        
        # Verify line totals computation
        line1 = offer["lines"][0]
        assert line1["activity_name"] == "Test Activity 1"
        assert line1["line_material_cost"] == 1000  # 10 * 100
        assert line1["line_labor_cost"] == 500  # 10 * 50
        assert line1["line_total"] == 1500  # 1000 + 500
        
        line2 = offer["lines"][1]
        assert line2["line_material_cost"] == 1000  # 5 * 200
        assert line2["line_labor_cost"] == 400  # 5 * 80
        assert line2["line_total"] == 1400  # 1000 + 400
        
        # Verify offer totals: subtotal = sum(line_totals) = 1500 + 1400 = 2900
        expected_subtotal = 2900
        expected_vat = 580  # 2900 * 0.20
        expected_total = 3480  # 2900 + 580
        
        assert offer["subtotal"] == expected_subtotal
        assert offer["vat_amount"] == expected_vat
        assert offer["total"] == expected_total
        
        print(f"Created offer {offer['offer_no']} with subtotal={offer['subtotal']}, vat={offer['vat_amount']}, total={offer['total']}")
    
    def test_get_offer(self, admin_headers):
        """GET /api/offers/{id} - Get single offer with project info"""
        assert TestOfferCRUD.created_offer_id, "No offer created"
        
        response = requests.get(f"{BASE_URL}/api/offers/{TestOfferCRUD.created_offer_id}", headers=admin_headers)
        assert response.status_code == 200
        
        offer = response.json()
        assert offer["id"] == TestOfferCRUD.created_offer_id
        assert "project_code" in offer
        assert "project_name" in offer
        print(f"Retrieved offer: {offer['offer_no']} for project {offer['project_code']}")
    
    def test_list_offers(self, admin_headers, test_project_id):
        """GET /api/offers - List offers with filters"""
        # List all offers
        response = requests.get(f"{BASE_URL}/api/offers", headers=admin_headers)
        assert response.status_code == 200
        offers = response.json()
        assert isinstance(offers, list)
        
        # Filter by project
        response = requests.get(f"{BASE_URL}/api/offers?project_id={test_project_id}", headers=admin_headers)
        assert response.status_code == 200
        filtered = response.json()
        for offer in filtered:
            assert offer["project_id"] == test_project_id
        
        # Filter by status
        response = requests.get(f"{BASE_URL}/api/offers?status=Draft", headers=admin_headers)
        assert response.status_code == 200
        draft_offers = response.json()
        for offer in draft_offers:
            assert offer["status"] == "Draft"
        
        print(f"Listed {len(offers)} total offers, {len(filtered)} for project, {len(draft_offers)} drafts")
    
    def test_update_draft_offer(self, admin_headers):
        """PUT /api/offers/{id} - Update draft offer metadata"""
        assert TestOfferCRUD.created_offer_id, "No offer created"
        
        payload = {
            "title": "TEST_Offer_Updated",
            "currency": "USD",
            "vat_percent": 15.0,
            "notes": "Updated notes"
        }
        
        response = requests.put(f"{BASE_URL}/api/offers/{TestOfferCRUD.created_offer_id}", headers=admin_headers, json=payload)
        assert response.status_code == 200
        
        offer = response.json()
        assert offer["title"] == "TEST_Offer_Updated"
        assert offer["currency"] == "USD"
        assert offer["vat_percent"] == 15.0
        
        # Verify totals recomputed with new VAT
        # Subtotal should remain 2900, VAT should now be 435 (2900 * 0.15)
        assert offer["subtotal"] == 2900
        assert offer["vat_amount"] == 435  # 2900 * 0.15
        assert offer["total"] == 3335  # 2900 + 435
        
        print(f"Updated offer VAT to 15%, new total: {offer['total']}")
    
    def test_update_offer_lines(self, admin_headers):
        """PUT /api/offers/{id}/lines - Update BOQ lines and verify recomputation"""
        assert TestOfferCRUD.created_offer_id, "No offer created"
        
        # New lines with different values
        payload = {
            "lines": [
                {
                    "activity_code": "NEW-001",
                    "activity_name": "New Activity",
                    "unit": "hours",
                    "qty": 20,
                    "material_unit_cost": 0,
                    "labor_unit_cost": 75,
                    "note": "Labor only line",
                    "sort_order": 0
                },
                {
                    "activity_code": "NEW-002",
                    "activity_name": "Material Purchase",
                    "unit": "lot",
                    "qty": 1,
                    "material_unit_cost": 5000,
                    "labor_unit_cost": 0,
                    "note": "Materials only",
                    "sort_order": 1
                }
            ]
        }
        
        response = requests.put(f"{BASE_URL}/api/offers/{TestOfferCRUD.created_offer_id}/lines", headers=admin_headers, json=payload)
        assert response.status_code == 200
        
        offer = response.json()
        assert len(offer["lines"]) == 2
        
        # Line 1: 20 * 75 = 1500 labor
        line1 = offer["lines"][0]
        assert line1["line_material_cost"] == 0
        assert line1["line_labor_cost"] == 1500
        assert line1["line_total"] == 1500
        
        # Line 2: 1 * 5000 = 5000 material
        line2 = offer["lines"][1]
        assert line2["line_material_cost"] == 5000
        assert line2["line_labor_cost"] == 0
        assert line2["line_total"] == 5000
        
        # Verify totals: subtotal = 1500 + 5000 = 6500, VAT 15% = 975
        assert offer["subtotal"] == 6500
        assert offer["vat_amount"] == 975  # 6500 * 0.15
        assert offer["total"] == 7475  # 6500 + 975
        
        print(f"Updated lines, new subtotal: {offer['subtotal']}, total: {offer['total']}")


class TestOfferStatusTransitions:
    """Test offer status transitions (send, accept, reject, version)"""
    
    status_test_offer_id = None
    
    def test_create_offer_for_status_tests(self, admin_headers, test_project_id):
        """Create offer for status transition tests"""
        payload = {
            "project_id": test_project_id,
            "title": "TEST_Status_Transitions",
            "currency": "EUR",
            "vat_percent": 20.0,
            "lines": [{
                "activity_name": "Status Test Line",
                "unit": "pcs",
                "qty": 1,
                "material_unit_cost": 100,
                "labor_unit_cost": 50
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json=payload)
        assert response.status_code == 201
        offer = response.json()
        TestOfferStatusTransitions.status_test_offer_id = offer["id"]
        assert offer["status"] == "Draft"
        print(f"Created status test offer: {offer['offer_no']}")
    
    def test_send_offer(self, admin_headers):
        """POST /api/offers/{id}/send - Change status to Sent"""
        offer_id = TestOfferStatusTransitions.status_test_offer_id
        assert offer_id, "No offer created"
        
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/send", headers=admin_headers)
        assert response.status_code == 200
        
        offer = response.json()
        assert offer["status"] == "Sent"
        assert offer["sent_at"] is not None
        print(f"Sent offer, status: {offer['status']}")
    
    def test_cannot_edit_sent_offer(self, admin_headers):
        """Sent offers cannot be edited"""
        offer_id = TestOfferStatusTransitions.status_test_offer_id
        assert offer_id, "No offer created"
        
        # Try to update
        response = requests.put(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers, json={"title": "New Title"})
        assert response.status_code == 403
        
        # Try to update lines
        response = requests.put(f"{BASE_URL}/api/offers/{offer_id}/lines", headers=admin_headers, json={"lines": []})
        assert response.status_code == 403
        print("Verified sent offer cannot be edited")
    
    def test_accept_offer_admin_only(self, admin_headers, tech_headers):
        """POST /api/offers/{id}/accept - Only Admin/Owner can accept"""
        offer_id = TestOfferStatusTransitions.status_test_offer_id
        assert offer_id, "No offer created"
        
        # Technician cannot accept
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/accept", headers=tech_headers)
        assert response.status_code == 403
        print("Verified technician cannot accept offer")
        
        # Admin can accept
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/accept", headers=admin_headers)
        assert response.status_code == 200
        
        offer = response.json()
        assert offer["status"] == "Accepted"
        assert offer["accepted_at"] is not None
        print(f"Admin accepted offer, status: {offer['status']}")
    
    def test_accepted_offer_locked(self, admin_headers):
        """Accepted offers cannot be edited"""
        offer_id = TestOfferStatusTransitions.status_test_offer_id
        assert offer_id, "No offer created"
        
        # Try to update
        response = requests.put(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers, json={"title": "New Title"})
        assert response.status_code == 403
        
        # Try to update lines
        response = requests.put(f"{BASE_URL}/api/offers/{offer_id}/lines", headers=admin_headers, json={"lines": []})
        assert response.status_code == 403
        
        # Cannot delete accepted offer
        response = requests.delete(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers)
        assert response.status_code == 400
        
        print("Verified accepted offer is locked")


class TestOfferVersioning:
    """Test offer versioning functionality"""
    
    version_test_offer_id = None
    new_version_offer_id = None
    
    def test_create_and_send_offer(self, admin_headers, test_project_id):
        """Create and send offer for versioning test"""
        payload = {
            "project_id": test_project_id,
            "title": "TEST_Versioning",
            "currency": "EUR",
            "vat_percent": 20.0,
            "lines": [{
                "activity_name": "Version Test Line",
                "unit": "pcs",
                "qty": 10,
                "material_unit_cost": 50,
                "labor_unit_cost": 25
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json=payload)
        assert response.status_code == 201
        offer = response.json()
        TestOfferVersioning.version_test_offer_id = offer["id"]
        
        # Send the offer
        response = requests.post(f"{BASE_URL}/api/offers/{offer['id']}/send", headers=admin_headers)
        assert response.status_code == 200
        print(f"Created and sent versioning test offer v1")
    
    def test_create_new_version(self, admin_headers):
        """POST /api/offers/{id}/new-version - Clone offer with incremented version"""
        offer_id = TestOfferVersioning.version_test_offer_id
        assert offer_id, "No offer created"
        
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/new-version", headers=admin_headers)
        assert response.status_code == 200
        
        new_offer = response.json()
        TestOfferVersioning.new_version_offer_id = new_offer["id"]
        
        # Verify version incremented
        assert new_offer["version"] == 2
        assert new_offer["status"] == "Draft"  # New version starts as Draft
        assert new_offer["parent_offer_id"] == offer_id  # Points to original
        
        # Verify same offer_no (versioning keeps offer_no)
        original = requests.get(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers).json()
        assert new_offer["offer_no"] == original["offer_no"]
        
        # Verify lines cloned with new IDs
        assert len(new_offer["lines"]) == len(original["lines"])
        for new_line, orig_line in zip(new_offer["lines"], original["lines"]):
            assert new_line["id"] != orig_line["id"]  # Different IDs
            assert new_line["activity_name"] == orig_line["activity_name"]  # Same data
        
        print(f"Created version 2, parent: {new_offer['parent_offer_id']}")
    
    def test_new_version_editable(self, admin_headers):
        """New version is Draft and can be edited"""
        offer_id = TestOfferVersioning.new_version_offer_id
        assert offer_id, "No new version created"
        
        # Can update
        response = requests.put(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers, json={
            "title": "TEST_Versioning v2 Updated"
        })
        assert response.status_code == 200
        assert response.json()["title"] == "TEST_Versioning v2 Updated"
        
        print("Verified new version is editable")


class TestOfferReject:
    """Test offer rejection flow"""
    
    reject_test_offer_id = None
    
    def test_create_and_send_offer(self, admin_headers, test_project_id):
        """Create and send offer for rejection test"""
        payload = {
            "project_id": test_project_id,
            "title": "TEST_Rejection",
            "currency": "EUR",
            "vat_percent": 10.0,
            "lines": [{
                "activity_name": "Reject Test Line",
                "unit": "m",
                "qty": 5,
                "material_unit_cost": 30,
                "labor_unit_cost": 20
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json=payload)
        assert response.status_code == 201
        offer_id = response.json()["id"]
        TestOfferReject.reject_test_offer_id = offer_id
        
        # Send
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/send", headers=admin_headers)
        assert response.status_code == 200
        print("Created and sent rejection test offer")
    
    def test_reject_offer(self, admin_headers):
        """POST /api/offers/{id}/reject - Reject sent offer"""
        offer_id = TestOfferReject.reject_test_offer_id
        assert offer_id, "No offer created"
        
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/reject", headers=admin_headers, json={
            "reason": "Price too high, need to renegotiate"
        })
        assert response.status_code == 200
        
        offer = response.json()
        assert offer["status"] == "Rejected"
        assert offer["reject_reason"] == "Price too high, need to renegotiate"
        print(f"Rejected offer with reason: {offer['reject_reason']}")
    
    def test_can_version_rejected_offer(self, admin_headers):
        """Can create new version from rejected offer"""
        offer_id = TestOfferReject.reject_test_offer_id
        assert offer_id, "No offer created"
        
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/new-version", headers=admin_headers)
        assert response.status_code == 200
        
        new_offer = response.json()
        assert new_offer["status"] == "Draft"
        assert new_offer["version"] == 2
        print("Created new version from rejected offer")


class TestActivityCatalog:
    """Test Activity Catalog CRUD"""
    
    activity_id = None
    
    def test_create_activity(self, admin_headers, test_project_id):
        """POST /api/activity-catalog - Create activity"""
        payload = {
            "project_id": test_project_id,
            "code": f"TEST-ACT-{uuid.uuid4().hex[:6].upper()}",
            "name": "TEST_Activity_AutoTest",
            "default_unit": "m2",
            "default_material_unit_cost": 45.50,
            "default_labor_unit_cost": 25.00,
            "default_labor_hours_per_unit": 0.5,
            "active": True
        }
        
        response = requests.post(f"{BASE_URL}/api/activity-catalog", headers=admin_headers, json=payload)
        assert response.status_code == 201
        
        activity = response.json()
        TestActivityCatalog.activity_id = activity["id"]
        
        assert activity["name"] == "TEST_Activity_AutoTest"
        assert activity["default_unit"] == "m2"
        assert activity["default_material_unit_cost"] == 45.50
        assert activity["default_labor_unit_cost"] == 25.00
        assert activity["active"] == True
        
        print(f"Created activity: {activity['code']} - {activity['name']}")
    
    def test_list_activities(self, admin_headers, test_project_id):
        """GET /api/activity-catalog - List activities"""
        # List all
        response = requests.get(f"{BASE_URL}/api/activity-catalog", headers=admin_headers)
        assert response.status_code == 200
        activities = response.json()
        assert isinstance(activities, list)
        
        # Filter by project
        response = requests.get(f"{BASE_URL}/api/activity-catalog?project_id={test_project_id}", headers=admin_headers)
        assert response.status_code == 200
        filtered = response.json()
        for act in filtered:
            assert act["project_id"] == test_project_id
        
        # Include inactive
        response = requests.get(f"{BASE_URL}/api/activity-catalog?active_only=false", headers=admin_headers)
        assert response.status_code == 200
        
        print(f"Listed {len(activities)} activities, {len(filtered)} for project")
    
    def test_update_activity(self, admin_headers):
        """PUT /api/activity-catalog/{id} - Update activity"""
        activity_id = TestActivityCatalog.activity_id
        assert activity_id, "No activity created"
        
        payload = {
            "name": "TEST_Activity_Updated",
            "default_labor_unit_cost": 30.00,
            "active": False
        }
        
        response = requests.put(f"{BASE_URL}/api/activity-catalog/{activity_id}", headers=admin_headers, json=payload)
        assert response.status_code == 200
        
        activity = response.json()
        assert activity["name"] == "TEST_Activity_Updated"
        assert activity["default_labor_unit_cost"] == 30.00
        assert activity["active"] == False
        
        print(f"Updated activity: {activity['name']}, active={activity['active']}")
    
    def test_delete_activity(self, admin_headers):
        """DELETE /api/activity-catalog/{id} - Delete activity"""
        activity_id = TestActivityCatalog.activity_id
        assert activity_id, "No activity created"
        
        response = requests.delete(f"{BASE_URL}/api/activity-catalog/{activity_id}", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["ok"] == True
        
        # Verify deleted
        response = requests.get(f"{BASE_URL}/api/activity-catalog/{activity_id}", headers=admin_headers)
        # Should not find it anymore (or 404)
        
        print("Deleted activity successfully")


class TestOfferEdgeCases:
    """Test edge cases and validation"""
    
    def test_cannot_send_empty_offer(self, admin_headers, test_project_id):
        """Cannot send offer without lines"""
        # Create offer without lines
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json={
            "project_id": test_project_id,
            "title": "TEST_Empty_Offer",
            "lines": []
        })
        assert response.status_code == 201
        offer_id = response.json()["id"]
        
        # Try to send - should fail
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/send", headers=admin_headers)
        assert response.status_code == 400
        assert "at least one line" in response.json()["detail"].lower()
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers)
        print("Verified cannot send offer without lines")
    
    def test_cannot_accept_draft_offer(self, admin_headers, test_project_id):
        """Cannot accept a draft offer"""
        # Create draft offer
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json={
            "project_id": test_project_id,
            "title": "TEST_Draft_Accept",
            "lines": [{"activity_name": "Test", "unit": "pcs", "qty": 1, "material_unit_cost": 10, "labor_unit_cost": 5}]
        })
        assert response.status_code == 201
        offer_id = response.json()["id"]
        
        # Try to accept - should fail (not in Sent status)
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/accept", headers=admin_headers)
        assert response.status_code == 400
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers)
        print("Verified cannot accept draft offer")
    
    def test_cannot_version_draft_offer(self, admin_headers, test_project_id):
        """Cannot create new version from draft offer"""
        # Create draft offer
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json={
            "project_id": test_project_id,
            "title": "TEST_Draft_Version",
            "lines": [{"activity_name": "Test", "unit": "pcs", "qty": 1, "material_unit_cost": 10, "labor_unit_cost": 5}]
        })
        assert response.status_code == 201
        offer_id = response.json()["id"]
        
        # Try to create new version - should fail
        response = requests.post(f"{BASE_URL}/api/offers/{offer_id}/new-version", headers=admin_headers)
        assert response.status_code == 400
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/offers/{offer_id}", headers=admin_headers)
        print("Verified cannot version draft offer")


class TestTotalsComputation:
    """Verify totals computation formula"""
    
    def test_totals_computation_accuracy(self, admin_headers, test_project_id):
        """
        Test formula: 
        - line_total = qty * (material_unit_cost + labor_unit_cost)
        - subtotal = sum(line_total)
        - vat_amount = subtotal * vat_percent / 100
        - total = subtotal + vat_amount
        """
        # Create offer with precise values
        payload = {
            "project_id": test_project_id,
            "title": "TEST_Totals_Computation",
            "currency": "EUR",
            "vat_percent": 19.0,  # Use 19% for variety
            "lines": [
                {
                    "activity_name": "Line A",
                    "unit": "m2",
                    "qty": 10,
                    "material_unit_cost": 25.50,  # Line total: 10 * (25.50 + 10.25) = 357.50
                    "labor_unit_cost": 10.25
                },
                {
                    "activity_name": "Line B",
                    "unit": "pcs",
                    "qty": 3,
                    "material_unit_cost": 150.00,  # Line total: 3 * (150 + 75) = 675
                    "labor_unit_cost": 75.00
                },
                {
                    "activity_name": "Line C",
                    "unit": "hours",
                    "qty": 8,
                    "material_unit_cost": 0,  # Line total: 8 * (0 + 55.50) = 444
                    "labor_unit_cost": 55.50
                }
            ]
        }
        
        response = requests.post(f"{BASE_URL}/api/offers", headers=admin_headers, json=payload)
        assert response.status_code == 201
        offer = response.json()
        
        # Expected calculations
        expected_line_a = 10 * (25.50 + 10.25)  # 357.50
        expected_line_b = 3 * (150.00 + 75.00)  # 675.00
        expected_line_c = 8 * (0 + 55.50)  # 444.00
        expected_subtotal = expected_line_a + expected_line_b + expected_line_c  # 1476.50
        expected_vat = round(expected_subtotal * 19 / 100, 2)  # 280.54
        expected_total = round(expected_subtotal + expected_vat, 2)  # 1757.04
        
        # Verify line totals
        assert offer["lines"][0]["line_total"] == round(expected_line_a, 2)
        assert offer["lines"][1]["line_total"] == round(expected_line_b, 2)
        assert offer["lines"][2]["line_total"] == round(expected_line_c, 2)
        
        # Verify offer totals
        assert offer["subtotal"] == round(expected_subtotal, 2)
        assert offer["vat_amount"] == expected_vat
        assert offer["total"] == expected_total
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/offers/{offer['id']}", headers=admin_headers)
        
        print(f"Verified totals: subtotal={offer['subtotal']}, vat={offer['vat_amount']}, total={offer['total']}")


class TestCleanup:
    """Cleanup test data"""
    
    def test_cleanup_test_offers(self, admin_headers):
        """Delete TEST_ prefixed offers"""
        response = requests.get(f"{BASE_URL}/api/offers", headers=admin_headers)
        if response.status_code == 200:
            offers = response.json()
            for offer in offers:
                if offer["title"].startswith("TEST_"):
                    try:
                        requests.delete(f"{BASE_URL}/api/offers/{offer['id']}", headers=admin_headers)
                    except:
                        pass
        print("Cleanup completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
