"""
Test Suite: Subcontractor Financial Flow (5 Phases)
- Phase 1: Subcontractors + Packages CRUD
- Phase 2: Package Lines with Over-Allocation Protection
- Phase 3: Subcontractor Acts (Certified Expense)
- Phase 4: Payments with Payable Math
- Phase 5: Integration into Project Profit
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Use existing project for testing
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001
OFFER_ID = "3fc7217c-4cc5-4e4b-bde7-71ad96c00b8b"  # existing offer linked to project


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestPhase1_SubcontractorsCRUD:
    """Phase 1: Subcontractors + Packages CRUD"""
    
    def test_p1_create_subcontractor(self, api_client):
        """P1: POST /api/subcontractors creates subcontractor"""
        payload = {
            "name": f"TEST_Subcontractor_{uuid.uuid4().hex[:8]}",
            "contact_person": "Test Contact",
            "phone": "+359888123456",
            "email": "test@subcontractor.com",
            "address": "Test Address 123"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractors", json=payload)
        
        assert response.status_code == 201, f"Failed to create subcontractor: {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "id" in data, "Response should contain id"
        assert data["name"] == payload["name"], "Name mismatch"
        assert data["contact_person"] == payload["contact_person"]
        assert data["active"] == True, "Subcontractor should be active by default"
        
        # Store for subsequent tests
        pytest.test_subcontractor_id = data["id"]
        print(f"Created subcontractor: {data['id']}")
    
    def test_p1_list_subcontractors(self, api_client):
        """GET /api/subcontractors lists all subcontractors"""
        response = api_client.get(f"{BASE_URL}/api/subcontractors")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert isinstance(data, list), "Response should be a list"
        assert len(data) >= 1, "Should have at least 1 subcontractor"
    
    def test_p1_get_subcontractor_by_id(self, api_client):
        """GET /api/subcontractors/{id} returns subcontractor detail"""
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        if not sub_id:
            pytest.skip("No subcontractor created yet")
        
        response = api_client.get(f"{BASE_URL}/api/subcontractors/{sub_id}")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data["id"] == sub_id
    
    def test_p1_create_draft_package(self, api_client):
        """P1: POST /api/subcontractor-packages creates draft package linked to project+subcontractor"""
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        if not sub_id:
            pytest.skip("No subcontractor created yet")
        
        payload = {
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": f"TEST_Package_{uuid.uuid4().hex[:8]}",
            "description": "Test package for subcontractor work",
            "currency": "EUR"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json=payload)
        
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        
        # Validate structure
        assert data["status"] == "draft", "New package should be draft"
        assert data["project_id"] == PROJECT_ID
        assert data["subcontractor_id"] == sub_id
        assert data["contract_total"] == 0
        assert data["certified_total"] == 0
        assert data["paid_total"] == 0
        assert data["payable_total"] == 0
        assert "package_no" in data, "Should have auto-generated package_no"
        
        pytest.test_package_id = data["id"]
        print(f"Created package: {data['package_no']} ({data['id']})")
    
    def test_p1_confirm_package_without_lines_fails(self, api_client):
        """P1: Confirm package without lines returns 400"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/confirm")
        
        assert response.status_code == 400, f"Should fail: {response.text}"
        assert "no lines" in response.text.lower(), "Should mention no lines"


class TestPhase2_PackageLines:
    """Phase 2: Package Lines with Over-Allocation Protection"""
    
    def test_p2_add_lines_to_package(self, api_client):
        """P2: POST /api/subcontractor-packages/{id}/lines adds lines with over-allocation check"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        payload = {
            "lines": [
                {
                    "activity_name": "TEST_Bosch_Work_Line1",
                    "unit": "m2",
                    "source_qty": 100,
                    "assigned_qty": 50,
                    "sale_unit_price": 25.0,
                    "subcontract_unit_price": 15.0
                },
                {
                    "activity_name": "TEST_Bosch_Work_Line2",
                    "unit": "бр",
                    "source_qty": 200,
                    "assigned_qty": 100,
                    "sale_unit_price": 10.0,
                    "subcontract_unit_price": 7.0
                }
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/lines", json=payload)
        
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        
        assert data["ok"] == True
        assert data["count"] == 2
        assert len(data["lines"]) == 2
        
        # Validate line calculations
        line1 = data["lines"][0]
        assert line1["assigned_qty"] == 50
        assert line1["subcontract_unit_price"] == 15.0
        assert line1["subcontract_total"] == 750.0  # 50 * 15
        assert line1["sale_total_for_assigned_qty"] == 1250.0  # 50 * 25
        assert line1["planned_margin"] == 500.0  # 50 * (25-15)
        assert line1["remaining_qty"] == 50  # assigned_qty initially
        
        # Store line IDs for later tests
        pytest.test_line_ids = [l["id"] for l in data["lines"]]
        print(f"Created {data['count']} lines")
    
    def test_p2_over_allocation_returns_400(self, api_client):
        """P2: Over-allocation returns 400 when assigned_qty exceeds free qty"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        # Try to add a line with offer_line_id that would exceed source_qty
        # First create a new package to test over-allocation
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        
        # Create temp package
        temp_pkg = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": "TEMP_Overallocation_Test",
            "currency": "EUR"
        })
        temp_pkg_id = temp_pkg.json()["id"]
        
        # Add line with low source_qty
        fake_offer_line_id = str(uuid.uuid4())
        api_client.post(f"{BASE_URL}/api/subcontractor-packages/{temp_pkg_id}/lines", json={
            "lines": [{
                "offer_line_id": fake_offer_line_id,
                "activity_name": "Test_Limited",
                "unit": "m2",
                "source_qty": 10,
                "assigned_qty": 10,
                "sale_unit_price": 10,
                "subcontract_unit_price": 5
            }]
        })
        
        # Create another package and try to over-allocate the same offer_line
        temp_pkg2 = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": "TEMP_Overallocation_Test2",
            "currency": "EUR"
        })
        temp_pkg2_id = temp_pkg2.json()["id"]
        
        # Try to assign more than available (source_qty=10, already assigned=10, free=0)
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{temp_pkg2_id}/lines", json={
            "lines": [{
                "offer_line_id": fake_offer_line_id,
                "activity_name": "Test_Limited",
                "unit": "m2",
                "source_qty": 10,
                "assigned_qty": 5,  # Request 5 but 0 free
                "sale_unit_price": 10,
                "subcontract_unit_price": 5
            }]
        })
        
        assert response.status_code == 400, f"Should fail with over-allocation: {response.text}"
        assert "over-allocation" in response.text.lower() or "free" in response.text.lower()
        print("Over-allocation protection working")
    
    def test_p2_delete_draft_line(self, api_client):
        """P2: DELETE /api/subcontractor-package-lines/{id} removes draft line"""
        line_ids = getattr(pytest, 'test_line_ids', None)
        if not line_ids or len(line_ids) < 2:
            pytest.skip("No lines to delete")
        
        # Delete the second line
        line_id = line_ids[1]
        response = api_client.delete(f"{BASE_URL}/api/subcontractor-package-lines/{line_id}")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data["ok"] == True
        
        # Update line_ids list
        pytest.test_line_ids = [line_ids[0]]
        print(f"Deleted line {line_id}")
    
    def test_p2_add_line_with_subcontract_price(self, api_client):
        """Add another line with proper subcontract_unit_price for act testing"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        payload = {
            "lines": [{
                "activity_name": "TEST_ActReady_Line",
                "unit": "m2",
                "source_qty": 100,
                "assigned_qty": 80,
                "sale_unit_price": 30.0,
                "subcontract_unit_price": 20.0  # Important for act testing
            }]
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/lines", json=payload)
        
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        
        # Store for act tests
        pytest.test_line_ids.append(data["lines"][0]["id"])
        print(f"Added line for act testing: {data['lines'][0]['id']}")


class TestPhase1_PackageConfirmAndClose:
    """Phase 1 continued: Package status transitions"""
    
    def test_p1_confirm_package_with_lines(self, api_client):
        """P1: POST /api/subcontractor-packages/{id}/confirm validates lines exist, changes status"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/confirm")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["status"] == "confirmed", "Status should be confirmed"
        assert data["contract_total"] > 0, "contract_total should be calculated"
        assert "confirmed_at" in data
        
        # Verify totals: line1=750 (50*15) + line2=1600 (80*20) = 2350
        expected_contract = 750 + 1600  # 2350
        assert data["contract_total"] == expected_contract, f"Contract total mismatch: {data['contract_total']} != {expected_contract}"
        assert data["remaining_contract_total"] == expected_contract
        
        print(f"Confirmed package with contract_total={data['contract_total']}")
    
    def test_p1_cannot_add_lines_to_confirmed_package(self, api_client):
        """Cannot add lines to confirmed package"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/lines", json={
            "lines": [{"activity_name": "Blocked", "unit": "m2", "assigned_qty": 10}]
        })
        
        assert response.status_code == 400, f"Should fail: {response.text}"
        assert "draft" in response.text.lower()


class TestPhase3_SubcontractorActs:
    """Phase 3: Subcontractor Acts (Certified Expense)"""
    
    def test_p3_create_draft_act(self, api_client):
        """P3: POST /api/subcontractor-acts creates draft act from package lines"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        line_ids = getattr(pytest, 'test_line_ids', None)
        if not pkg_id or not line_ids:
            pytest.skip("No package or lines created yet")
        
        payload = {
            "package_id": pkg_id,
            "act_date": "2026-03-15",
            "notes": "Test act for certified work",
            "lines": [
                {"package_line_id": line_ids[0], "current_certified_qty": 25},  # 50% of line1
                {"package_line_id": line_ids[1], "current_certified_qty": 40}   # 50% of line2
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-acts", json=payload)
        
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        
        assert data["status"] == "draft"
        assert data["package_id"] == pkg_id
        assert "act_no" in data
        assert len(data["lines"]) == 2
        
        # Validate certified_total: (25*15) + (40*20) = 375 + 800 = 1175
        expected_certified = 375 + 800
        assert data["certified_total"] == expected_certified, f"Certified total mismatch: {data['certified_total']}"
        
        pytest.test_act_id = data["id"]
        print(f"Created act: {data['act_no']} with certified_total={data['certified_total']}")
    
    def test_p3_certification_qty_exceeds_remaining_returns_400(self, api_client):
        """P3: Certification qty cannot exceed remaining qty (returns 400)"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        line_ids = getattr(pytest, 'test_line_ids', None)
        if not pkg_id or not line_ids:
            pytest.skip("No package or lines created yet")
        
        # Try to certify more than remaining (line1 has 50 assigned, requesting 100)
        payload = {
            "package_id": pkg_id,
            "lines": [{"package_line_id": line_ids[0], "current_certified_qty": 100}]  # Exceeds remaining
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-acts", json=payload)
        
        assert response.status_code == 400, f"Should fail: {response.text}"
        assert "exceeds" in response.text.lower() or "remaining" in response.text.lower()
        print("Certification qty limit protection working")
    
    def test_p3_confirm_act_updates_package_totals(self, api_client):
        """P3: POST /api/subcontractor-acts/{id}/confirm updates package line certified_qty and package totals"""
        act_id = getattr(pytest, 'test_act_id', None)
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not act_id:
            pytest.skip("No act created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-acts/{act_id}/confirm")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["status"] == "confirmed"
        assert "confirmed_at" in data
        
        # Verify package was updated
        pkg_response = api_client.get(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}")
        pkg = pkg_response.json()
        
        # certified_total should now be 1175
        assert pkg["certified_total"] == 1175, f"Package certified_total mismatch: {pkg['certified_total']}"
        # payable_total = certified - paid (paid is 0)
        assert pkg["payable_total"] == 1175, f"Package payable_total mismatch: {pkg['payable_total']}"
        
        print(f"Act confirmed. Package certified_total={pkg['certified_total']}, payable_total={pkg['payable_total']}")
    
    def test_p3_package_status_transition(self, api_client):
        """P3: Package status transitions: confirmed → partially_certified → completed"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        pkg_response = api_client.get(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}")
        pkg = pkg_response.json()
        
        # After partial certification, status should be partially_certified
        assert pkg["status"] == "partially_certified", f"Status should be partially_certified, got: {pkg['status']}"
        print(f"Package status: {pkg['status']}")


class TestPhase4_Payments:
    """Phase 4: Subcontractor Payments with Payable Math"""
    
    def test_p4_create_payment(self, api_client):
        """P4: POST /api/subcontractor-payments creates payment and updates paid_total"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        payload = {
            "package_id": pkg_id,
            "amount": 500.0,
            "payment_date": "2026-03-16",
            "payment_type": "partial",
            "payment_method": "bank",
            "notes": "Test payment #1"
        }
        response = api_client.post(f"{BASE_URL}/api/subcontractor-payments", json=payload)
        
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        
        assert data["amount"] == 500.0
        assert data["package_id"] == pkg_id
        assert "payment_no" in data
        assert data["status"] == "completed"
        
        pytest.test_payment_id = data["id"]
        print(f"Created payment: {data['payment_no']} for {data['amount']} EUR")
    
    def test_p4_payable_total_calculation(self, api_client):
        """P4: payable_total = certified_total - paid_total"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        pkg_response = api_client.get(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}")
        pkg = pkg_response.json()
        
        # certified=1175, paid=500, payable should be 675
        expected_payable = 1175 - 500
        assert pkg["paid_total"] == 500, f"paid_total mismatch: {pkg['paid_total']}"
        assert pkg["payable_total"] == expected_payable, f"payable_total mismatch: {pkg['payable_total']}"
        
        print(f"Payable math: certified={pkg['certified_total']} - paid={pkg['paid_total']} = payable={pkg['payable_total']}")
    
    def test_p4_list_payments(self, api_client):
        """List payments for package"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.get(f"{BASE_URL}/api/subcontractor-payments", params={"package_id": pkg_id})
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) >= 1
        print(f"Found {len(data)} payment(s) for package")


class TestPhase5_ProfitIntegration:
    """Phase 5: Integration into Project Profit"""
    
    def test_p5_project_profit_includes_subcontract_detail(self, api_client):
        """P5: GET /api/project-profit/{id} includes subcontract_detail with committed/certified/paid/payable"""
        response = api_client.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["project_id"] == PROJECT_ID
        assert "expenses" in data
        assert "subcontract_detail" in data["expenses"]
        
        sub_detail = data["expenses"]["subcontract_detail"]
        if sub_detail:  # May be None if no confirmed packages
            assert "committed" in sub_detail, "Should have committed"
            assert "certified" in sub_detail, "Should have certified"
            assert "paid" in sub_detail, "Should have paid"
            assert "payable" in sub_detail, "Should have payable"
            assert sub_detail["available"] == True
            
            print(f"Subcontract detail: committed={sub_detail['committed']}, certified={sub_detail['certified']}, paid={sub_detail['paid']}, payable={sub_detail['payable']}")
    
    def test_p5_metrics_available_subcontract_cost(self, api_client):
        """P5: metrics_available.subcontract_cost reflects real subcontractor data"""
        response = api_client.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "metrics_available" in data
        assert "subcontract_cost" in data["metrics_available"]
        
        # Should be True since we have confirmed packages
        assert data["metrics_available"]["subcontract_cost"] == True, "subcontract_cost metric should be available"
        
        # Subcontract cost in expenses should reflect certified amount
        sub_cost = data["expenses"]["subcontract"]
        assert sub_cost > 0, f"Subcontract cost should be > 0, got {sub_cost}"
        
        print(f"Subcontract cost: {sub_cost} EUR")


class TestPhase1_PackageClose:
    """Phase 1: Package Close"""
    
    def test_p1_close_package_on_confirmed(self, api_client):
        """P1: POST /api/subcontractor-packages/{id}/close works on confirmed/completed packages"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/close")
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["status"] == "closed"
        assert "closed_at" in data
        print(f"Closed package: {data['package_no']}")
    
    def test_p1_cannot_close_draft_package(self, api_client):
        """Cannot close a draft package"""
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        if not sub_id:
            pytest.skip("No subcontractor created yet")
        
        # Create a new draft package
        draft_pkg = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": "TEMP_Draft_NoClose"
        })
        draft_id = draft_pkg.json()["id"]
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{draft_id}/close")
        
        assert response.status_code == 400, f"Should fail: {response.text}"
        assert "draft" in response.text.lower()
        print("Draft package cannot be closed - protection working")


class TestLinesFromOffer:
    """Phase 2: Lines from Offer"""
    
    def test_p2_lines_from_offer(self, api_client):
        """P2: POST /api/subcontractor-packages/{id}/lines-from-offer/{offer_id} populates from offer"""
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        if not sub_id:
            pytest.skip("No subcontractor created yet")
        
        # Create a new package for this test
        pkg_response = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": "TEST_FromOffer_Package",
            "source_offer_id": OFFER_ID
        })
        
        assert pkg_response.status_code == 201
        pkg_id = pkg_response.json()["id"]
        
        # Try to add lines from offer
        response = api_client.post(f"{BASE_URL}/api/subcontractor-packages/{pkg_id}/lines-from-offer/{OFFER_ID}")
        
        # Could be 201 with lines or 201 with empty if all offer lines already assigned
        if response.status_code == 201:
            data = response.json()
            print(f"Added {data.get('count', 0)} lines from offer")
        else:
            # May fail if no free qty available
            print(f"Lines from offer result: {response.status_code} - {response.text[:200]}")


class TestEdgeCases:
    """Edge cases and error handling"""
    
    def test_package_not_found(self, api_client):
        """404 for non-existent package"""
        fake_id = str(uuid.uuid4())
        response = api_client.get(f"{BASE_URL}/api/subcontractor-packages/{fake_id}")
        assert response.status_code == 404
    
    def test_subcontractor_not_found(self, api_client):
        """404 for non-existent subcontractor"""
        fake_id = str(uuid.uuid4())
        response = api_client.get(f"{BASE_URL}/api/subcontractors/{fake_id}")
        assert response.status_code == 404
    
    def test_act_on_draft_package_fails(self, api_client):
        """Cannot create act on draft package"""
        sub_id = getattr(pytest, 'test_subcontractor_id', None)
        if not sub_id:
            pytest.skip("No subcontractor created yet")
        
        # Create draft package
        draft_pkg = api_client.post(f"{BASE_URL}/api/subcontractor-packages", json={
            "project_id": PROJECT_ID,
            "subcontractor_id": sub_id,
            "title": "TEMP_Draft_NoAct"
        })
        draft_id = draft_pkg.json()["id"]
        
        # Try to create act
        response = api_client.post(f"{BASE_URL}/api/subcontractor-acts", json={
            "package_id": draft_id,
            "lines": []
        })
        
        assert response.status_code == 400, f"Should fail: {response.text}"
        assert "confirmed" in response.text.lower() or "draft" in response.text.lower()
    
    def test_payment_zero_amount_fails(self, api_client):
        """Payment with 0 amount fails"""
        pkg_id = getattr(pytest, 'test_package_id', None)
        if not pkg_id:
            pytest.skip("No package created yet")
        
        response = api_client.post(f"{BASE_URL}/api/subcontractor-payments", json={
            "package_id": pkg_id,
            "amount": 0
        })
        
        assert response.status_code == 400, f"Should fail: {response.text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
