"""
Test procurement module endpoints:
- Material Requests CRUD + from-offer generation
- Supplier Invoice create/review/correction
- Post to Warehouse flow
- Warehouse transactions list
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Known test data from context
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001


@pytest.fixture(scope="module")
def auth_token():
    """Get auth token for testing"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MATERIAL REQUESTS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMaterialRequests:
    """Tests for Material Requests CRUD endpoints"""
    
    created_request_id = None
    
    def test_create_material_request(self, auth_headers):
        """POST /api/material-requests creates request with lines and project link"""
        payload = {
            "project_id": PROJECT_ID,
            "stage_name": "TEST_STAGE_Procurement",
            "needed_date": "2026-02-15",
            "notes": "TEST_MR - Procurement testing",
            "lines": [
                {
                    "material_name": "TEST_Material_1",
                    "category": "Строителни материали",
                    "qty_requested": 10,
                    "unit": "бр",
                    "notes": "Test line 1"
                },
                {
                    "material_name": "TEST_Material_2",
                    "category": "Инструменти",
                    "qty_requested": 5,
                    "unit": "м2",
                    "notes": "Test line 2"
                }
            ]
        }
        
        resp = requests.post(f"{BASE_URL}/api/material-requests", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Create MR failed: {resp.text}"
        
        data = resp.json()
        assert "id" in data
        assert data["project_id"] == PROJECT_ID
        assert data["stage_name"] == "TEST_STAGE_Procurement"
        assert data["status"] == "draft"
        assert data["request_number"].startswith("MR-")
        assert len(data["lines"]) == 2
        
        # Store for cleanup
        TestMaterialRequests.created_request_id = data["id"]
        print(f"Created MR: {data['request_number']} (id={data['id']})")
    
    def test_list_material_requests(self, auth_headers):
        """GET /api/material-requests lists requests with project info"""
        resp = requests.get(f"{BASE_URL}/api/material-requests", headers=auth_headers)
        assert resp.status_code == 200, f"List MR failed: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1, "Should have at least 1 material request"
        
        # Check first item has expected fields
        mr = data[0]
        assert "id" in mr
        assert "request_number" in mr
        assert "project_id" in mr
        assert "project_code" in mr or mr.get("project_code") == ""
        assert "status" in mr
        print(f"Found {len(data)} material requests")
    
    def test_get_single_material_request(self, auth_headers):
        """GET /api/material-requests/{id} returns full request"""
        if not TestMaterialRequests.created_request_id:
            pytest.skip("No created request to get")
        
        resp = requests.get(
            f"{BASE_URL}/api/material-requests/{TestMaterialRequests.created_request_id}",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Get MR failed: {resp.text}"
        
        data = resp.json()
        assert data["id"] == TestMaterialRequests.created_request_id
        assert len(data["lines"]) == 2
        print(f"Got MR: {data['request_number']}")
    
    def test_update_material_request(self, auth_headers):
        """PUT /api/material-requests/{id} updates request"""
        if not TestMaterialRequests.created_request_id:
            pytest.skip("No created request to update")
        
        update_payload = {
            "notes": "TEST_MR - Updated notes",
            "stage_name": "TEST_STAGE_Updated"
        }
        
        resp = requests.put(
            f"{BASE_URL}/api/material-requests/{TestMaterialRequests.created_request_id}",
            json=update_payload,
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Update MR failed: {resp.text}"
        
        data = resp.json()
        assert data["notes"] == "TEST_MR - Updated notes"
        assert data["stage_name"] == "TEST_STAGE_Updated"
        print(f"Updated MR: {data['request_number']}")
    
    def test_submit_material_request(self, auth_headers):
        """POST /api/material-requests/{id}/submit changes status to submitted"""
        if not TestMaterialRequests.created_request_id:
            pytest.skip("No created request to submit")
        
        resp = requests.post(
            f"{BASE_URL}/api/material-requests/{TestMaterialRequests.created_request_id}/submit",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Submit MR failed: {resp.text}"
        
        data = resp.json()
        assert data["status"] == "submitted"
        print(f"Submitted MR: {data['request_number']}")


# ═══════════════════════════════════════════════════════════════════════════════
# MATERIAL REQUEST FROM OFFER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMaterialRequestFromOffer:
    """Tests for generating MR from offer"""
    
    offer_id = None
    mr_from_offer_id = None
    
    def test_create_offer_for_mr_test(self, auth_headers):
        """Create an offer first to test from-offer endpoint"""
        # Create a draft offer
        offer_payload = {
            "project_id": PROJECT_ID,
            "title": "TEST_OFFER_FOR_MR",
            "currency": "BGN",
            "vat_percent": 20,
            "notes": "Test offer for material request generation",
            "lines": [
                {
                    "activity_name": "TEST_Activity_1",
                    "unit": "m2",
                    "qty": 100,
                    "material_unit_cost": 15.0,
                    "labor_unit_cost": 10.0,
                    "sort_order": 0
                },
                {
                    "activity_name": "TEST_Activity_2",
                    "unit": "pcs",
                    "qty": 50,
                    "material_unit_cost": 25.0,
                    "labor_unit_cost": 5.0,
                    "sort_order": 1
                }
            ]
        }
        
        resp = requests.post(f"{BASE_URL}/api/offers", json=offer_payload, headers=auth_headers)
        if resp.status_code != 201:
            print(f"Create offer response: {resp.text}")
        assert resp.status_code == 201, f"Create offer failed: {resp.text}"
        
        data = resp.json()
        TestMaterialRequestFromOffer.offer_id = data["id"]
        print(f"Created offer: {data.get('offer_no', data['id'])}")
    
    def test_send_offer_to_make_it_sent(self, auth_headers):
        """Send offer to enable MR from offer (requires Sent or Accepted status)"""
        if not TestMaterialRequestFromOffer.offer_id:
            pytest.skip("No offer created")
        
        resp = requests.post(
            f"{BASE_URL}/api/offers/{TestMaterialRequestFromOffer.offer_id}/send",
            headers=auth_headers
        )
        # May be 200 or 400 if already sent
        if resp.status_code == 200:
            print("Offer sent successfully")
        elif resp.status_code == 400:
            print(f"Offer send response: {resp.text}")
    
    def test_accept_offer(self, auth_headers):
        """Accept offer to enable MR from offer"""
        if not TestMaterialRequestFromOffer.offer_id:
            pytest.skip("No offer created")
        
        resp = requests.post(
            f"{BASE_URL}/api/offers/{TestMaterialRequestFromOffer.offer_id}/accept",
            headers=auth_headers
        )
        # May be 200 or 400 if not in Sent status
        if resp.status_code == 200:
            print("Offer accepted")
        else:
            print(f"Accept offer response: {resp.status_code}")
    
    def test_create_mr_from_offer(self, auth_headers):
        """POST /api/material-requests/from-offer/{id} generates request from offer lines"""
        if not TestMaterialRequestFromOffer.offer_id:
            pytest.skip("No offer created")
        
        payload = {
            "stage_name": "TEST_FROM_OFFER_Stage",
            "needed_date": "2026-03-01"
        }
        
        resp = requests.post(
            f"{BASE_URL}/api/material-requests/from-offer/{TestMaterialRequestFromOffer.offer_id}",
            json=payload,
            headers=auth_headers
        )
        assert resp.status_code == 201, f"Create MR from offer failed: {resp.text}"
        
        data = resp.json()
        assert "id" in data
        assert data["source_offer_id"] == TestMaterialRequestFromOffer.offer_id
        assert data["project_id"] == PROJECT_ID
        assert len(data["lines"]) >= 2  # Should have at least offer lines
        
        TestMaterialRequestFromOffer.mr_from_offer_id = data["id"]
        print(f"Created MR from offer: {data['request_number']} with {len(data['lines'])} lines")


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPLIER INVOICE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupplierInvoices:
    """Tests for Supplier Invoice create/review/correction"""
    
    created_invoice_id = None
    
    def test_create_supplier_invoice(self, auth_headers):
        """POST /api/supplier-invoices creates supplier invoice record"""
        inv_number = f"SF-TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        payload = {
            "supplier_name": "TEST_Supplier ABC",
            "invoice_number": inv_number,
            "invoice_date": "2026-01-20",
            "project_id": PROJECT_ID,
            "purchased_by": "Test User",
            "notes": "TEST_INVOICE for procurement testing"
        }
        
        resp = requests.post(f"{BASE_URL}/api/supplier-invoices", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Create invoice failed: {resp.text}"
        
        data = resp.json()
        assert "id" in data
        assert data["invoice_number"] == inv_number
        assert data["supplier_name"] == "TEST_Supplier ABC"
        assert data["status"] == "uploaded"
        assert data["posted_to_warehouse"] is False
        
        TestSupplierInvoices.created_invoice_id = data["id"]
        print(f"Created supplier invoice: {data['invoice_number']} (id={data['id']})")
    
    def test_list_supplier_invoices(self, auth_headers):
        """GET /api/supplier-invoices lists invoices"""
        resp = requests.get(f"{BASE_URL}/api/supplier-invoices", headers=auth_headers)
        assert resp.status_code == 200, f"List invoices failed: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1, "Should have at least 1 invoice"
        
        # Check first item has expected fields
        inv = data[0]
        assert "id" in inv
        assert "invoice_number" in inv
        assert "status" in inv
        print(f"Found {len(data)} supplier invoices")
    
    def test_get_single_invoice(self, auth_headers):
        """GET /api/supplier-invoices/{id} returns full invoice"""
        if not TestSupplierInvoices.created_invoice_id:
            pytest.skip("No created invoice to get")
        
        resp = requests.get(
            f"{BASE_URL}/api/supplier-invoices/{TestSupplierInvoices.created_invoice_id}",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Get invoice failed: {resp.text}"
        
        data = resp.json()
        assert data["id"] == TestSupplierInvoices.created_invoice_id
        print(f"Got invoice: {data['invoice_number']}")
    
    def test_update_invoice_with_lines_sets_reviewed(self, auth_headers):
        """PUT /api/supplier-invoices/{id} with lines updates status to 'reviewed', computes totals"""
        if not TestSupplierInvoices.created_invoice_id:
            pytest.skip("No created invoice to update")
        
        update_payload = {
            "lines": [
                {
                    "material_name": "TEST_Material_Cement",
                    "qty": 10,
                    "unit": "бр",
                    "unit_price": 50.0,
                    "discount_percent": 10
                },
                {
                    "material_name": "TEST_Material_Sand",
                    "qty": 5,
                    "unit": "т",
                    "unit_price": 100.0,
                    "discount_percent": 0
                }
            ],
            "status": "reviewed"
        }
        
        resp = requests.put(
            f"{BASE_URL}/api/supplier-invoices/{TestSupplierInvoices.created_invoice_id}",
            json=update_payload,
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Update invoice failed: {resp.text}"
        
        data = resp.json()
        assert data["status"] == "reviewed"
        assert len(data["lines"]) == 2
        
        # Verify totals computed with discount
        # Line 1: 10 * 50 * 0.9 = 450
        # Line 2: 5 * 100 * 1.0 = 500
        # Subtotal: 950, VAT 20%: 190, Total: 1140
        assert data["subtotal"] == 950.0
        assert data["total"] == 1140.0  # 950 + 190 VAT
        
        # Check discount applied correctly in lines
        line1 = data["lines"][0]
        assert line1["final_unit_price"] == 45.0  # 50 * 0.9
        assert line1["total_price"] == 450.0
        
        print(f"Updated invoice with lines, status={data['status']}, subtotal={data['subtotal']}, total={data['total']}")


# ═══════════════════════════════════════════════════════════════════════════════
# POST TO WAREHOUSE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPostToWarehouse:
    """Tests for posting invoice to warehouse"""
    
    posted_invoice_id = None
    transaction_id = None
    
    def test_create_and_review_invoice_for_posting(self, auth_headers):
        """Create and review invoice to prepare for warehouse posting"""
        inv_number = f"SF-POST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create
        create_resp = requests.post(f"{BASE_URL}/api/supplier-invoices", json={
            "supplier_name": "TEST_Supplier For Posting",
            "invoice_number": inv_number,
            "invoice_date": "2026-01-22",
            "project_id": PROJECT_ID,
            "notes": "TEST_INVOICE for warehouse posting"
        }, headers=auth_headers)
        assert create_resp.status_code == 201
        inv_id = create_resp.json()["id"]
        
        # Add lines and review
        update_resp = requests.put(f"{BASE_URL}/api/supplier-invoices/{inv_id}", json={
            "lines": [
                {"material_name": "TEST_Posting_Material_1", "qty": 20, "unit": "бр", "unit_price": 30.0, "discount_percent": 5},
                {"material_name": "TEST_Posting_Material_2", "qty": 15, "unit": "м", "unit_price": 40.0, "discount_percent": 0}
            ],
            "status": "reviewed"
        }, headers=auth_headers)
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "reviewed"
        
        TestPostToWarehouse.posted_invoice_id = inv_id
        print(f"Created and reviewed invoice {inv_number} for posting")
    
    def test_post_invoice_to_warehouse(self, auth_headers):
        """POST /api/supplier-invoices/{id}/post-to-warehouse creates warehouse transaction"""
        if not TestPostToWarehouse.posted_invoice_id:
            pytest.skip("No invoice prepared for posting")
        
        resp = requests.post(
            f"{BASE_URL}/api/supplier-invoices/{TestPostToWarehouse.posted_invoice_id}/post-to-warehouse",
            headers=auth_headers
        )
        assert resp.status_code == 201, f"Post to warehouse failed: {resp.text}"
        
        data = resp.json()
        assert "id" in data
        assert data["type"] == "intake"
        assert data["source_type"] == "supplier_invoice"
        assert data["source_invoice_id"] == TestPostToWarehouse.posted_invoice_id
        assert data["project_id"] == PROJECT_ID
        assert len(data["lines"]) == 2
        
        # Check lines have required fields
        line1 = data["lines"][0]
        assert "material_name" in line1
        assert "qty_received" in line1
        assert "unit_price" in line1
        assert "final_unit_price" in line1
        
        TestPostToWarehouse.transaction_id = data["id"]
        print(f"Created warehouse transaction: {data['id']} with {len(data['lines'])} lines")
    
    def test_cannot_post_same_invoice_twice(self, auth_headers):
        """Cannot post same invoice twice (posted_to_warehouse check)"""
        if not TestPostToWarehouse.posted_invoice_id:
            pytest.skip("No posted invoice")
        
        resp = requests.post(
            f"{BASE_URL}/api/supplier-invoices/{TestPostToWarehouse.posted_invoice_id}/post-to-warehouse",
            headers=auth_headers
        )
        assert resp.status_code == 400, "Should return 400 for already posted invoice"
        assert "Already posted" in resp.text or "вече" in resp.text.lower()
        print("Correctly rejected duplicate posting")
    
    def test_invoice_marked_as_posted(self, auth_headers):
        """Verify invoice is marked as posted_to_warehouse after posting"""
        if not TestPostToWarehouse.posted_invoice_id:
            pytest.skip("No posted invoice")
        
        resp = requests.get(
            f"{BASE_URL}/api/supplier-invoices/{TestPostToWarehouse.posted_invoice_id}",
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        assert data["posted_to_warehouse"] is True
        assert data["status"] == "posted_to_warehouse"
        assert "warehouse_transaction_id" in data
        print(f"Invoice marked as posted, warehouse_transaction_id={data['warehouse_transaction_id']}")


# ═══════════════════════════════════════════════════════════════════════════════
# WAREHOUSE TRANSACTIONS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestWarehouseTransactions:
    """Tests for warehouse transactions listing"""
    
    def test_list_warehouse_transactions(self, auth_headers):
        """GET /api/warehouse-transactions lists intake transactions"""
        resp = requests.get(f"{BASE_URL}/api/warehouse-transactions", headers=auth_headers)
        assert resp.status_code == 200, f"List transactions failed: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1, "Should have at least 1 transaction after posting"
        
        # Check first item has expected fields
        txn = data[0]
        assert "id" in txn
        assert "type" in txn
        assert "warehouse_id" in txn
        assert "lines" in txn
        print(f"Found {len(data)} warehouse transactions")
    
    def test_warehouse_transaction_has_links(self, auth_headers):
        """Warehouse transaction links to: supplier, invoice, project, request"""
        resp = requests.get(f"{BASE_URL}/api/warehouse-transactions", headers=auth_headers)
        assert resp.status_code == 200
        
        data = resp.json()
        # Find a transaction with source_invoice_id
        for txn in data:
            if txn.get("source_invoice_id"):
                assert "supplier_id" in txn or "supplier_name" in txn
                assert "source_invoice_id" in txn
                assert "project_id" in txn
                print(f"Transaction {txn['id']} has links: invoice={txn.get('source_invoice_id')}, project={txn.get('project_id')}")
                return
        
        print("No transaction with invoice link found (may be expected)")


# ═══════════════════════════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

class TestCleanup:
    """Cleanup test data"""
    
    def test_cleanup_test_data(self, auth_headers):
        """Delete TEST_ prefixed material requests and invoices"""
        # Get all material requests and delete TEST_ ones in draft status
        resp = requests.get(f"{BASE_URL}/api/material-requests", headers=auth_headers)
        if resp.status_code == 200:
            for mr in resp.json():
                if mr.get("notes", "").startswith("TEST_") or mr.get("stage_name", "").startswith("TEST_"):
                    if mr.get("status") == "draft":
                        del_resp = requests.delete(
                            f"{BASE_URL}/api/material-requests/{mr['id']}",
                            headers=auth_headers
                        )
                        if del_resp.status_code == 200:
                            print(f"Deleted MR: {mr.get('request_number')}")
        
        # Note: Invoices and warehouse transactions don't have delete endpoints typically
        # They would need to be cleaned up via database directly
        print("Cleanup completed (draft MRs deleted)")
