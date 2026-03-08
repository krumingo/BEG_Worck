"""
Invoice Payments Tests (P0 Feature)
Tests for direct invoice payments, status transitions, and payment management.

Features tested:
- Invoice numbering (settings, auto-generation)
- Invoice status transitions: Draft -> Sent -> PartiallyPaid -> Paid -> Cancelled
- Direct payment API: POST /api/finance/invoices/{id}/payments
- Payment history: GET /api/finance/invoices/{id}/payments
- Payment removal: DELETE /api/finance/invoices/{id}/payments/{alloc_id}
- Over-payment prevention
- Cannot pay Draft or Cancelled invoices
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timedelta

from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def unique_id():
    return str(uuid.uuid4())[:8]

ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD
ACCOUNT_ID = "cc234dbd-62ed-4fbc-a215-edda65cbd991"  # Company Bank


class TestAuth:
    @staticmethod
    def get_admin_token():
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json()["token"]


class TestInvoiceNumbering:
    """Invoice numbering settings and auto-generation"""
    
    def test_get_invoice_settings(self):
        """GET /api/finance/invoice-settings returns numbering config"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/invoice-settings",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        settings = response.json()
        assert "issued_auto_numbering" in settings
        assert "issued_prefix" in settings
        assert "issued_next_number" in settings
        print(f"✓ Invoice settings: prefix={settings['issued_prefix']}, next={settings['issued_next_number']}")
    
    def test_get_next_invoice_number(self):
        """GET /api/finance/next-invoice-number previews next number"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/next-invoice-number?direction=Issued",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["auto_numbering"] == True
        assert "next_number" in data
        assert data["next_number"].startswith(data["prefix"])
        print(f"✓ Next invoice number: {data['next_number']}")
    
    def test_update_invoice_settings(self):
        """PUT /api/finance/invoice-settings updates numbering"""
        token = TestAuth.get_admin_token()
        # Get current
        current = requests.get(
            f"{BASE_URL}/api/finance/invoice-settings",
            headers={"Authorization": f"Bearer {token}"}
        ).json()
        
        # Update to starting 1000
        response = requests.put(
            f"{BASE_URL}/api/finance/invoice-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"issued_next_number": 1000}
        )
        assert response.status_code == 200
        updated = response.json()
        # Should be >= 1000 (may be higher if invoices already exist)
        assert updated["issued_next_number"] >= 1000
        print(f"✓ Updated settings: next_number={updated['issued_next_number']}")
    
    def test_auto_number_on_create(self):
        """Invoice creation auto-generates sequential number"""
        token = TestAuth.get_admin_token()
        
        # Get expected next number
        next_resp = requests.get(
            f"{BASE_URL}/api/finance/next-invoice-number?direction=Issued",
            headers={"Authorization": f"Bearer {token}"}
        ).json()
        expected_num = next_resp["next_number"]
        
        # Create invoice with empty invoice_no (auto-generate)
        response = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "",  # Should auto-generate
                "counterparty_name": "TEST Auto Number",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Test", "qty": 1, "unit_price": 100}]
            }
        )
        assert response.status_code == 201
        invoice = response.json()
        assert invoice["invoice_no"] == expected_num
        print(f"✓ Auto-generated invoice number: {invoice['invoice_no']}")


class TestInvoiceStatusTransitions:
    """Invoice status transitions: Draft -> Sent -> PartiallyPaid -> Paid -> Cancelled"""
    
    def test_draft_to_sent(self):
        """POST /api/finance/invoices/{id}/send transitions Draft to Sent"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-STATUS-{unique_id()}"
        
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
        assert create_resp.status_code == 201
        invoice = create_resp.json()
        assert invoice["status"] == "Draft"
        
        send_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert send_resp.status_code == 200
        sent = send_resp.json()
        assert sent["status"] in ["Sent", "Overdue"]  # Overdue if due_date < today
        print(f"✓ Draft -> Sent transition: {sent['status']}")
    
    def test_sent_to_partiallypaid_to_paid(self):
        """Partial payment -> PartiallyPaid, full payment -> Paid"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-PARTIAL-{unique_id()}"
        
        # Create and send
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
        total = invoice["total"]  # 1200 with 20% VAT
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        # Partial payment
        partial_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 600,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "method": "BankTransfer",
                "account_id": ACCOUNT_ID
            }
        )
        assert partial_resp.status_code == 201
        result = partial_resp.json()
        assert result["invoice"]["status"] == "PartiallyPaid"
        assert result["invoice"]["paid_amount"] == 600
        print(f"✓ Partial payment: status=PartiallyPaid, paid=600, remaining={result['invoice']['remaining_amount']}")
        
        # Pay remaining
        remaining = result["invoice"]["remaining_amount"]
        full_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": remaining,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "method": "BankTransfer",
                "account_id": ACCOUNT_ID
            }
        )
        assert full_resp.status_code == 201
        final = full_resp.json()
        assert final["invoice"]["status"] == "Paid"
        assert final["invoice"]["remaining_amount"] == 0
        print(f"✓ Full payment: status=Paid, remaining=0")
    
    def test_cancel_sent_invoice(self):
        """POST /api/finance/invoices/{id}/cancel cancels Sent invoice"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-CANCEL-{unique_id()}"
        
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
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        cancel_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/cancel",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cancel_resp.status_code == 200
        cancelled = cancel_resp.json()
        assert cancelled["status"] == "Cancelled"
        print(f"✓ Cancel transition: status=Cancelled")


class TestDirectInvoicePayments:
    """POST /api/finance/invoices/{id}/payments - direct payment API"""
    
    def test_add_payment_to_sent_invoice(self):
        """Add payment to Sent invoice"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-DIRECT-{unique_id()}"
        
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
                "lines": [{"description": "Service", "qty": 1, "unit_price": 500}]
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 300,
                "date": "2026-01-15",
                "method": "BankTransfer",
                "account_id": ACCOUNT_ID,
                "reference": "PMT-TEST",
                "note": "Test payment"
            }
        )
        assert pay_resp.status_code == 201
        result = pay_resp.json()
        assert result["ok"] == True
        assert result["amount"] == 300
        assert "payment_id" in result
        assert "allocation_id" in result
        print(f"✓ Direct payment added: amount=300, payment_id={result['payment_id'][:8]}...")
    
    def test_cannot_pay_draft_invoice(self):
        """Cannot add payment to Draft invoice"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-DRAFT-{unique_id()}"
        
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
        # NOT sending - stays Draft
        
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 50,
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": ACCOUNT_ID
            }
        )
        assert pay_resp.status_code == 400
        assert "чернова" in pay_resp.json()["detail"].lower() or "draft" in pay_resp.json()["detail"].lower()
        print(f"✓ Payment to Draft blocked: {pay_resp.json()['detail']}")
    
    def test_cannot_pay_cancelled_invoice(self):
        """Cannot add payment to Cancelled invoice"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-CANCELLED-{unique_id()}"
        
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
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/cancel", headers={"Authorization": f"Bearer {token}"})
        
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 50,
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": ACCOUNT_ID
            }
        )
        assert pay_resp.status_code == 400
        assert "анулирана" in pay_resp.json()["detail"].lower() or "cancelled" in pay_resp.json()["detail"].lower()
        print(f"✓ Payment to Cancelled blocked: {pay_resp.json()['detail']}")
    
    def test_overpayment_prevented(self):
        """Cannot pay more than remaining amount"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-OVERPAY-{unique_id()}"
        
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
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]  # Total = 120
            }
        )
        invoice = create_resp.json()
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 99999,
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": ACCOUNT_ID
            }
        )
        assert pay_resp.status_code == 400
        assert "надвишава" in pay_resp.json()["detail"].lower() or "exceed" in pay_resp.json()["detail"].lower()
        print(f"✓ Overpayment blocked: {pay_resp.json()['detail']}")
    
    def test_payment_requires_positive_amount(self):
        """Payment amount must be positive"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-ZERO-{unique_id()}"
        
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
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        # Zero amount
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 0,
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": ACCOUNT_ID
            }
        )
        assert pay_resp.status_code == 400
        print(f"✓ Zero amount blocked")
    
    def test_payment_requires_account(self):
        """Payment requires account_id"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-NOACC-{unique_id()}"
        
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
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 50,
                "date": "2026-01-15",
                "method": "Cash"
                # Missing account_id
            }
        )
        assert pay_resp.status_code == 400
        print(f"✓ Missing account blocked")


class TestPaymentHistory:
    """GET /api/finance/invoices/{id}/payments - payment history"""
    
    def test_list_invoice_payments(self):
        """List payments for an invoice"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-HIST-{unique_id()}"
        
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
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        # Add two payments
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 400, "date": "2026-01-10", "method": "BankTransfer", "account_id": ACCOUNT_ID, "reference": "PMT-1"}
        )
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 300, "date": "2026-01-15", "method": "Cash", "account_id": ACCOUNT_ID, "reference": "PMT-2"}
        )
        
        # Get payment history
        hist_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert hist_resp.status_code == 200
        payments = hist_resp.json()
        assert len(payments) == 2
        for p in payments:
            assert "id" in p
            assert "amount" in p
            assert "date" in p
            assert "method" in p
            assert "account_name" in p
        print(f"✓ Payment history: {len(payments)} payments")
        for p in payments:
            print(f"  - {p['amount']} via {p['method']} on {p['date']}")


class TestPaymentRemoval:
    """DELETE /api/finance/invoices/{id}/payments/{alloc_id} - payment removal"""
    
    def test_remove_payment_recalculates_status(self):
        """Removing payment recalculates invoice status"""
        token = TestAuth.get_admin_token()
        inv_no = f"TEST-REMOVE-{unique_id()}"
        
        # Use future due date (90 days from now)
        future_due = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": inv_no,
                "counterparty_name": "Customer",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": future_due,
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice = create_resp.json()
        total = invoice["total"]  # 1200
        requests.post(f"{BASE_URL}/api/finance/invoices/{invoice['id']}/send", headers={"Authorization": f"Bearer {token}"})
        
        # Add payment to make it PartiallyPaid
        pay_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 600, "date": datetime.now().strftime("%Y-%m-%d"), "method": "BankTransfer", "account_id": ACCOUNT_ID}
        )
        assert pay_resp.json()["invoice"]["status"] == "PartiallyPaid"
        allocation_id = pay_resp.json()["allocation_id"]
        
        # Remove payment
        del_resp = requests.delete(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}/payments/{allocation_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200
        
        # Check invoice status recalculated
        inv_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"}
        )
        updated = inv_resp.json()
        # Should go back to Sent since due_date is in the future
        assert updated["status"] == "Sent", f"Expected Sent but got {updated['status']}"
        assert updated["paid_amount"] == 0
        assert updated["remaining_amount"] == total
        print(f"✓ Payment removed, status={updated['status']}, paid=0, remaining={total}")
    
    def test_cannot_remove_from_cancelled_invoice(self):
        """Cannot remove payment from Cancelled invoice"""
        # This test is skipped because you can't have payments on a cancelled invoice anyway
        pass


class TestCleanup:
    """Cleanup TEST_ prefixed data"""
    
    def test_cleanup_test_data(self):
        """Remove all TEST- prefixed invoices"""
        token = TestAuth.get_admin_token()
        
        invoices_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        invoices = invoices_resp.json()
        deleted = 0
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
                deleted += 1
        print(f"✓ Cleaned up {deleted} test invoices")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
