"""
Invoice Workflow P0 Tests - Complete Invoice Workflow Fix
Tests for: 
1) PDF export
2) Invoice editing rules for Sent/PartiallyPaid/Overdue/Paid/Cancelled statuses
3) Payment→Project financial sync
4) Project dashboard invoice totals
5) Status consistency

Test invoice INV-1007 (ID: 2d83596a-102a-4c35-8618-fbfb11928b73) is PartiallyPaid with project acbc1503-849f-4e0d-8207-9d20b99e0c23
Account ID: cc234dbd-62ed-4fbc-a215-edda65cbd991
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timedelta

from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD
ACCOUNT_ID = "cc234dbd-62ed-4fbc-a215-edda65cbd991"  # Company Bank
TEST_PROJECT_ID = "acbc1503-849f-4e0d-8207-9d20b99e0c23"  # Test project
TEST_INVOICE_ID = "2d83596a-102a-4c35-8618-fbfb11928b73"  # INV-1007 PartiallyPaid

def unique_id():
    return str(uuid.uuid4())[:8]


class TestAuth:
    @staticmethod
    def get_admin_token():
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json()["token"]


class TestInvoicePDFExport:
    """Test PDF export functionality"""
    
    def test_pdf_endpoint_returns_pdf(self):
        """GET /api/finance/invoices/{id}/pdf returns valid PDF"""
        token = TestAuth.get_admin_token()
        
        # First, get any existing invoice
        invoices_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert invoices_resp.status_code == 200
        invoices = invoices_resp.json()
        
        if len(invoices) > 0:
            invoice_id = invoices[0]["id"]
            
            # Request PDF
            pdf_resp = requests.get(
                f"{BASE_URL}/api/finance/invoices/{invoice_id}/pdf",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert pdf_resp.status_code == 200, f"PDF export failed: {pdf_resp.text}"
            assert pdf_resp.headers.get("content-type") == "application/pdf"
            # Check it starts with PDF magic bytes
            assert pdf_resp.content[:4] == b"%PDF", "Response is not a valid PDF"
            print(f"✓ PDF export successful: {len(pdf_resp.content)} bytes")
        else:
            print("⚠ No invoices to test PDF export")
    
    def test_pdf_404_for_invalid_invoice(self):
        """PDF export returns 404 for non-existent invoice"""
        token = TestAuth.get_admin_token()
        
        pdf_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/nonexistent-id/pdf",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert pdf_resp.status_code == 404
        print("✓ PDF export returns 404 for invalid invoice")


class TestInvoiceEditingRules:
    """Test invoice editing based on status"""
    
    def test_edit_sent_invoice_allowed(self):
        """Sent invoice can be edited (notes, dates, lines, counterparty)"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-EDIT-SENT-{unique_id()}"
        
        # Create and send invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Original Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Edit counterparty and notes
        edit_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "counterparty_name": "Updated Customer Name",
                "notes": "Updated notes for sent invoice"
            }
        )
        assert edit_resp.status_code == 200, f"Edit failed: {edit_resp.text}"
        updated = edit_resp.json()
        assert updated["counterparty_name"] == "Updated Customer Name"
        assert updated["notes"] == "Updated notes for sent invoice"
        print(f"✓ Sent invoice edit allowed: counterparty updated")
        
        # Edit lines
        lines_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/lines",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "lines": [
                    {"description": "Updated Service", "qty": 2, "unit_price": 500}
                ]
            }
        )
        assert lines_resp.status_code == 200, f"Lines edit failed: {lines_resp.text}"
        updated_lines = lines_resp.json()
        assert updated_lines["subtotal"] == 1000
        print(f"✓ Sent invoice lines edit allowed: new subtotal={updated_lines['subtotal']}")
    
    def test_edit_partiallypaid_invoice_allowed(self):
        """PartiallyPaid invoice can be edited"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-EDIT-PP-{unique_id()}"
        
        # Create, send, and partial pay
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Partial payment
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 500, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Verify status
        inv_resp = requests.get(f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
                                headers={"Authorization": f"Bearer {token}"})
        assert inv_resp.json()["status"] == "PartiallyPaid"
        
        # Edit notes (should work)
        edit_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"notes": "Edited notes on partially paid invoice"}
        )
        assert edit_resp.status_code == 200, f"Edit failed: {edit_resp.text}"
        print(f"✓ PartiallyPaid invoice edit allowed")
    
    def test_edit_partiallypaid_invoice_lines_recalculates_remaining(self):
        """Editing lines on PartiallyPaid invoice recalculates remaining_amount"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-EDIT-PP-LINES-{unique_id()}"
        
        # Create, send, and partial pay
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]  # Total=1200
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Partial payment of 500
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 500, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Edit lines to increase total
        lines_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/lines",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "lines": [
                    {"description": "More Service", "qty": 2, "unit_price": 1000}  # Total=2400
                ]
            }
        )
        assert lines_resp.status_code == 200, f"Lines edit failed: {lines_resp.text}"
        updated = lines_resp.json()
        
        # New total = 2000 * 1.2 = 2400, paid = 500, remaining = 1900
        assert updated["total"] == 2400
        assert updated["paid_amount"] == 500
        assert updated["remaining_amount"] == 1900
        print(f"✓ PartiallyPaid lines edit recalculates: total={updated['total']}, remaining={updated['remaining_amount']}")
    
    def test_edit_paid_invoice_blocked(self):
        """Paid invoice cannot be edited - returns error"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-EDIT-PAID-{unique_id()}"
        
        # Create, send, and fully pay
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]  # Total=120
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Full payment
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 120, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Verify status is Paid
        inv_resp = requests.get(f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
                                headers={"Authorization": f"Bearer {token}"})
        assert inv_resp.json()["status"] == "Paid"
        
        # Try to edit - should fail
        edit_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"notes": "Trying to edit paid invoice"}
        )
        assert edit_resp.status_code == 400, f"Edit should be blocked but got {edit_resp.status_code}"
        assert "платени" in edit_resp.json()["detail"].lower() or "paid" in edit_resp.json()["detail"].lower()
        print(f"✓ Paid invoice edit blocked: {edit_resp.json()['detail']}")
    
    def test_edit_cancelled_invoice_blocked(self):
        """Cancelled invoice cannot be edited - returns error"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-EDIT-CANCEL-{unique_id()}"
        
        # Create, send, and cancel
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/cancel", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Try to edit - should fail
        edit_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"notes": "Trying to edit cancelled invoice"}
        )
        assert edit_resp.status_code == 400, f"Edit should be blocked but got {edit_resp.status_code}"
        assert "анулирани" in edit_resp.json()["detail"].lower() or "cancel" in edit_resp.json()["detail"].lower()
        print(f"✓ Cancelled invoice edit blocked: {edit_resp.json()['detail']}")


class TestProjectDashboardFinancials:
    """Test project dashboard financial sync with invoices"""
    
    def test_dashboard_returns_correct_paid_unpaid_totals(self):
        """Project dashboard totals match actual invoice paid_amount values"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-PROJ-DASH-{unique_id()}"
        
        # Create a new project
        proj_code = f"TP-{unique_id()}"
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": proj_code,
                "name": "Test Project Dashboard",
                "status": "Active",
                "type": "Billable"
            }
        )
        assert proj_resp.status_code == 201, f"Project creation failed: {proj_resp.text}"
        project = proj_resp.json()
        project_id = project["id"]
        
        # Create invoice linked to project
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Project Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Project Work", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        total = invoice["total"]  # 1200
        
        # Send invoice
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Check dashboard before payment
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert dash_resp.status_code == 200
        dash = dash_resp.json()
        
        # Before payment: paid=0, unpaid=total
        assert dash["invoices"]["totals"]["paid"] == 0
        assert dash["invoices"]["totals"]["unpaid"] == total
        print(f"✓ Before payment: paid={dash['invoices']['totals']['paid']}, unpaid={dash['invoices']['totals']['unpaid']}")
        
        # Add partial payment
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 600, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Check dashboard after partial payment
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash = dash_resp.json()
        
        # After partial payment: paid=600, unpaid=600
        assert dash["invoices"]["totals"]["paid"] == 600
        assert dash["invoices"]["totals"]["unpaid"] == total - 600
        print(f"✓ After partial payment: paid={dash['invoices']['totals']['paid']}, unpaid={dash['invoices']['totals']['unpaid']}")
        
        # Balance income should reflect paid amount
        assert dash["balance"]["income"] == 600, f"Balance income should be 600 but got {dash['balance']['income']}"
        print(f"✓ Balance income matches paid: {dash['balance']['income']}")
    
    def test_full_payment_reflects_in_project_financials(self):
        """Full payment updates project dashboard correctly"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-PROJ-FULL-{unique_id()}"
        
        # Create project
        proj_code = f"TF-{unique_id()}"
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": proj_code,
                "name": "Test Full Payment Project",
                "status": "Active",
                "type": "Billable"
            }
        )
        project = proj_resp.json()
        project_id = project["id"]
        
        # Create and send invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Work", "qty": 1, "unit_price": 500}]  # Total=600
            }
        )
        invoice = create_resp.json()
        total = invoice["total"]
        
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Full payment
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": total, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Check dashboard
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash = dash_resp.json()
        
        assert dash["invoices"]["totals"]["paid"] == total
        assert dash["invoices"]["totals"]["unpaid"] == 0
        assert dash["balance"]["income"] == total
        print(f"✓ Full payment: paid={total}, unpaid=0, balance income={total}")
    
    def test_payment_removal_updates_project_financials(self):
        """Removing payment updates project dashboard"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-PROJ-REMOVE-{unique_id()}"
        
        # Create project
        proj_code = f"TR-{unique_id()}"
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": proj_code,
                "name": "Test Remove Payment Project",
                "status": "Active",
                "type": "Billable"
            }
        )
        project = proj_resp.json()
        project_id = project["id"]
        
        # Create and send invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Work", "qty": 1, "unit_price": 500}]
            }
        )
        invoice = create_resp.json()
        total = invoice["total"]
        
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        
        # Add and then remove payment
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 300, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        allocation_id = pay_resp.json()["allocation_id"]
        
        # Remove payment
        requests.delete(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments/{allocation_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Check dashboard
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash = dash_resp.json()
        
        assert dash["invoices"]["totals"]["paid"] == 0
        assert dash["invoices"]["totals"]["unpaid"] == total
        assert dash["balance"]["income"] == 0
        print(f"✓ After payment removal: paid=0, unpaid={total}, balance income=0")


class TestInvoiceTableColumns:
    """Test project invoice table returns correct columns"""
    
    def test_dashboard_invoices_have_correct_fields(self):
        """Dashboard invoice list includes paid_amount, remaining_amount, status"""
        token = TestAuth.get_admin_token()
        
        # Use existing test project or create new
        inv_no = f"TEST-COLS-{unique_id()}"
        proj_code = f"TC-{unique_id()}"
        
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": proj_code,
                "name": "Test Columns Project",
                "status": "Active",
                "type": "Billable"
            }
        )
        project = proj_resp.json()
        project_id = project["id"]
        
        # Create invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Customer ABC",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Work", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        
        # Send and partial pay
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 500, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Get dashboard
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash = dash_resp.json()
        
        # Check invoice has required fields
        assert len(dash["invoices"]["invoices"]) > 0
        inv = dash["invoices"]["invoices"][0]
        
        # Required columns for project invoice table
        assert "invoice_no" in inv
        assert "client_name" in inv or "counterparty_name" in inv
        assert "issue_date" in inv
        assert "due_date" in inv
        assert "status" in inv
        assert "total" in inv
        assert "paid_amount" in inv
        assert "remaining_amount" in inv
        
        print(f"✓ Invoice columns present:")
        print(f"  - invoice_no: {inv['invoice_no']}")
        print(f"  - client_name: {inv.get('client_name', 'N/A')}")
        print(f"  - status: {inv['status']}")
        print(f"  - total: {inv['total']}")
        print(f"  - paid_amount: {inv['paid_amount']}")
        print(f"  - remaining_amount: {inv['remaining_amount']}")


class TestStatusConsistency:
    """Test status consistency between invoice and project views"""
    
    def test_partiallypaid_shows_correct_amounts(self):
        """PartiallyPaid invoice shows same paid_amount in both invoice and project"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-CONSIST-{unique_id()}"
        
        # Create project
        proj_code = f"TCON-{unique_id()}"
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={"code": proj_code, "name": "Consistency Test", "status": "Active", "type": "Billable"}
        )
        project_id = proj_resp.json()["id"]
        
        # Create, send, partial pay
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Work", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        invoice_id = invoice["id"]
        
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice_id}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 750, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Get invoice directly
        inv_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        inv_data = inv_resp.json()
        
        # Get from project dashboard
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash_inv = next(i for i in dash_resp.json()["invoices"]["invoices"] if i["id"] == invoice_id)
        
        # Compare
        assert inv_data["paid_amount"] == dash_inv["paid_amount"], \
            f"Mismatch: invoice paid={inv_data['paid_amount']}, dashboard paid={dash_inv['paid_amount']}"
        assert inv_data["remaining_amount"] == dash_inv["remaining_amount"], \
            f"Mismatch: invoice remaining={inv_data['remaining_amount']}, dashboard remaining={dash_inv['remaining_amount']}"
        assert inv_data["status"] == dash_inv["status"], \
            f"Mismatch: invoice status={inv_data['status']}, dashboard status={dash_inv['status']}"
        
        print(f"✓ Consistency verified:")
        print(f"  - Invoice: paid={inv_data['paid_amount']}, remaining={inv_data['remaining_amount']}, status={inv_data['status']}")
        print(f"  - Dashboard: paid={dash_inv['paid_amount']}, remaining={dash_inv['remaining_amount']}, status={dash_inv['status']}")
    
    def test_paid_invoice_shows_zero_remaining(self):
        """Paid invoice shows 0 remaining in both views"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-PAID-ZERO-{unique_id()}"
        
        # Create project
        proj_code = f"TPZ-{unique_id()}"
        proj_resp = requests.post(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={"code": proj_code, "name": "Paid Zero Test", "status": "Active", "type": "Billable"}
        )
        project_id = proj_resp.json()["id"]
        
        # Create, send, full pay
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "project_id": project_id,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Work", "qty": 1, "unit_price": 100}]  # Total=120
            }
        )
        invoice = create_resp.json()
        invoice_id = invoice["id"]
        total = invoice["total"]
        
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice_id}/send", 
                      headers={"Authorization": f"Bearer {token}"})
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": total, "date": datetime.now().strftime("%Y-%m-%d"), 
                  "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        
        # Get invoice
        inv_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        inv_data = inv_resp.json()
        
        # Get from dashboard
        dash_resp = requests.get(
            f"{BASE_URL}/api/projects/{project_id}/dashboard",
            headers={"Authorization": f"Bearer {token}"}
        )
        dash_inv = next(i for i in dash_resp.json()["invoices"]["invoices"] if i["id"] == invoice_id)
        
        # Verify both show 0 remaining
        assert inv_data["remaining_amount"] == 0
        assert dash_inv["remaining_amount"] == 0
        assert inv_data["status"] == "Paid"
        assert dash_inv["status"] == "Paid"
        
        print(f"✓ Paid invoice shows 0 remaining in both views")


class TestCleanup:
    """Cleanup TEST_ prefixed data"""
    
    def test_cleanup_test_data(self):
        """Remove all TEST- prefixed invoices and projects"""
        token = TestAuth.get_admin_token()
        
        # Cleanup invoices
        invoices_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        invoices = invoices_resp.json()
        deleted_inv = 0
        for inv in invoices:
            if inv.get("invoice_no", "").startswith("TEST-"):
                if inv["status"] not in ["Draft"]:
                    requests.post(
                        f"{BASE_URL}/api/finance/invoices/{inv['id']}/cancel",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                requests.delete(
                    f"{BASE_URL}/api/finance/invoices/{inv['id']}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                deleted_inv += 1
        
        # Cleanup projects
        projects_resp = requests.get(
            f"{BASE_URL}/api/projects",
            headers={"Authorization": f"Bearer {token}"}
        )
        projects = projects_resp.json()
        deleted_proj = 0
        for proj in projects:
            if proj.get("code", "").startswith("T") and len(proj.get("code", "")) <= 12:
                requests.delete(
                    f"{BASE_URL}/api/projects/{proj['id']}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                deleted_proj += 1
        
        print(f"✓ Cleaned up {deleted_inv} test invoices and {deleted_proj} test projects")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
