"""
M5 Finance Module Tests
Tests for Financial Accounts, Invoices, Payments, and Allocations
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "admin123"
TECH_EMAIL = "tech@begwork.com"  # Technician with no finance access
TECH_PASSWORD = "tech123"


class TestAuth:
    """Authentication helpers"""
    
    @staticmethod
    def get_admin_token():
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json()["token"]
    
    @staticmethod
    def get_tech_token():
        """Get technician auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TECH_EMAIL,
            "password": TECH_PASSWORD
        })
        if response.status_code == 200:
            return response.json()["token"]
        return None


class TestFinanceStats:
    """Finance Statistics endpoint"""
    
    def test_get_finance_stats_as_admin(self):
        """Admin can get finance stats"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/stats",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        # Validate response structure
        assert "receivables_total" in data
        assert "receivables_count" in data
        assert "payables_total" in data
        assert "payables_count" in data
        assert "cash_balance" in data
        assert "bank_balance" in data
        print(f"✓ Finance stats retrieved: Receivables={data['receivables_total']}, Payables={data['payables_total']}, Cash={data['cash_balance']}, Bank={data['bank_balance']}")
    
    def test_get_finance_stats_blocked_for_technician(self):
        """Technician blocked from finance stats"""
        token = TestAuth.get_tech_token()
        if not token:
            pytest.skip("Technician user not available")
        response = requests.get(
            f"{BASE_URL}/api/finance/stats",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        print("✓ Technician correctly blocked from finance stats")


class TestFinancialAccounts:
    """Financial Accounts CRUD"""
    
    def test_list_accounts_as_admin(self):
        """Admin can list financial accounts"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        accounts = response.json()
        assert isinstance(accounts, list)
        print(f"✓ Listed {len(accounts)} financial accounts")
        for acc in accounts:
            assert "id" in acc
            assert "name" in acc
            assert "type" in acc
            assert "current_balance" in acc
            print(f"  - {acc['name']} ({acc['type']}): Balance={acc['current_balance']} {acc.get('currency', 'EUR')}")
    
    def test_create_account(self):
        """Admin can create financial account"""
        token = TestAuth.get_admin_token()
        response = requests.post(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "TEST_Petty Cash",
                "type": "Cash",
                "currency": "EUR",
                "opening_balance": 500.00,
                "active": True
            }
        )
        assert response.status_code == 201
        account = response.json()
        assert account["name"] == "TEST_Petty Cash"
        assert account["type"] == "Cash"
        assert account["opening_balance"] == 500.00
        print(f"✓ Created account: {account['name']} (ID: {account['id']})")
        return account["id"]
    
    def test_update_account(self):
        """Admin can update financial account"""
        token = TestAuth.get_admin_token()
        # First create an account
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "TEST_Update Account",
                "type": "Bank",
                "currency": "EUR",
                "opening_balance": 1000.00
            }
        )
        assert create_resp.status_code == 201
        account_id = create_resp.json()["id"]
        
        # Update it
        update_resp = requests.put(
            f"{BASE_URL}/api/finance/accounts/{account_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "TEST_Updated Account Name",
                "opening_balance": 1500.00
            }
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["name"] == "TEST_Updated Account Name"
        assert updated["opening_balance"] == 1500.00
        print(f"✓ Updated account: {updated['name']}")
    
    def test_delete_account_without_payments(self):
        """Admin can delete account without payments"""
        token = TestAuth.get_admin_token()
        # Create an account
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "TEST_To Be Deleted",
                "type": "Cash",
                "currency": "EUR",
                "opening_balance": 0
            }
        )
        assert create_resp.status_code == 201
        account_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(
            f"{BASE_URL}/api/finance/accounts/{account_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_resp.status_code == 200
        print(f"✓ Deleted account: {account_id}")
    
    def test_technician_blocked_from_accounts(self):
        """Technician blocked from accounts"""
        token = TestAuth.get_tech_token()
        if not token:
            pytest.skip("Technician user not available")
        response = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        print("✓ Technician correctly blocked from accounts")


class TestInvoices:
    """Invoice CRUD and workflow"""
    
    def test_list_invoices_as_admin(self):
        """Admin can list invoices"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        invoices = response.json()
        assert isinstance(invoices, list)
        print(f"✓ Listed {len(invoices)} invoices")
        for inv in invoices[:5]:  # Show first 5
            print(f"  - {inv['invoice_no']} ({inv['direction']}/{inv['status']}): {inv.get('total', 0)} {inv.get('currency', 'EUR')}")
    
    def test_filter_invoices_by_direction(self):
        """Filter invoices by direction"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/invoices?direction=Issued",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        invoices = response.json()
        for inv in invoices:
            assert inv["direction"] == "Issued"
        print(f"✓ Filtered to {len(invoices)} Issued invoices")
    
    def test_filter_invoices_by_status(self):
        """Filter invoices by status"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/invoices?status=Paid",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        invoices = response.json()
        for inv in invoices:
            assert inv["status"] == "Paid"
        print(f"✓ Filtered to {len(invoices)} Paid invoices")
    
    def test_create_issued_invoice(self):
        """Admin can create issued invoice (Sales)"""
        token = TestAuth.get_admin_token()
        response = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-INV-001",
                "counterparty_name": "TEST Customer Ltd",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "notes": "Test invoice",
                "lines": [
                    {
                        "description": "Consulting services",
                        "unit": "hours",
                        "qty": 10,
                        "unit_price": 100.00
                    },
                    {
                        "description": "Materials",
                        "unit": "pcs",
                        "qty": 5,
                        "unit_price": 50.00
                    }
                ]
            }
        )
        assert response.status_code == 201
        invoice = response.json()
        assert invoice["invoice_no"] == "TEST-INV-001"
        assert invoice["direction"] == "Issued"
        assert invoice["status"] == "Draft"
        # Validate calculations: 10*100 + 5*50 = 1250, VAT 20% = 250, Total = 1500
        assert invoice["subtotal"] == 1250.00
        assert invoice["vat_amount"] == 250.00
        assert invoice["total"] == 1500.00
        assert invoice["remaining_amount"] == 1500.00
        print(f"✓ Created invoice: {invoice['invoice_no']}, Total={invoice['total']} EUR")
        return invoice["id"]
    
    def test_create_received_invoice(self):
        """Admin can create received invoice (Bill)"""
        token = TestAuth.get_admin_token()
        response = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Received",
                "invoice_no": "TEST-BILL-001",
                "counterparty_name": "TEST Supplier Inc",
                "issue_date": "2026-01-10",
                "due_date": "2026-02-10",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [
                    {
                        "description": "Raw materials",
                        "unit": "kg",
                        "qty": 100,
                        "unit_price": 5.00
                    }
                ]
            }
        )
        assert response.status_code == 201
        invoice = response.json()
        assert invoice["invoice_no"] == "TEST-BILL-001"
        assert invoice["direction"] == "Received"
        assert invoice["status"] == "Draft"
        # 100 * 5 = 500, VAT 20% = 100, Total = 600
        assert invoice["total"] == 600.00
        print(f"✓ Created bill: {invoice['invoice_no']}, Total={invoice['total']} EUR")
        return invoice["id"]
    
    def test_get_invoice_details(self):
        """Get single invoice with details"""
        token = TestAuth.get_admin_token()
        # Get any invoice
        list_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        invoices = list_resp.json()
        if not invoices:
            pytest.skip("No invoices available")
        
        invoice_id = invoices[0]["id"]
        response = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        invoice = response.json()
        assert "lines" in invoice
        assert "allocations" in invoice
        print(f"✓ Retrieved invoice details: {invoice['invoice_no']} with {len(invoice['lines'])} lines")
    
    def test_update_draft_invoice(self):
        """Update draft invoice"""
        token = TestAuth.get_admin_token()
        # Create a draft invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-UPDATE-001",
                "counterparty_name": "Original Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Item", "qty": 1, "unit_price": 100}]
            }
        )
        assert create_resp.status_code == 201
        invoice_id = create_resp.json()["id"]
        
        # Update it
        update_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "counterparty_name": "Updated Customer",
                "notes": "Updated notes"
            }
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["counterparty_name"] == "Updated Customer"
        assert updated["notes"] == "Updated notes"
        print(f"✓ Updated invoice: {updated['invoice_no']}")
    
    def test_update_invoice_lines(self):
        """Update invoice lines"""
        token = TestAuth.get_admin_token()
        # Create a draft invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-LINES-001",
                "counterparty_name": "Test",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Original Item", "qty": 1, "unit_price": 100}]
            }
        )
        assert create_resp.status_code == 201
        invoice_id = create_resp.json()["id"]
        
        # Update lines
        lines_resp = requests.put(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/lines",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "lines": [
                    {"description": "New Item 1", "unit": "pcs", "qty": 2, "unit_price": 200},
                    {"description": "New Item 2", "unit": "hours", "qty": 5, "unit_price": 50}
                ]
            }
        )
        assert lines_resp.status_code == 200
        updated = lines_resp.json()
        # 2*200 + 5*50 = 650, VAT 20% = 130, Total = 780
        assert updated["subtotal"] == 650.00
        assert updated["total"] == 780.00
        print(f"✓ Updated invoice lines: new total={updated['total']} EUR")
    
    def test_send_invoice(self):
        """Send draft invoice"""
        token = TestAuth.get_admin_token()
        # Create a draft invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-SEND-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 500}]
            }
        )
        assert create_resp.status_code == 201
        invoice_id = create_resp.json()["id"]
        
        # Send it
        send_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert send_resp.status_code == 200
        sent = send_resp.json()
        assert sent["status"] == "Sent"
        assert "sent_at" in sent
        print(f"✓ Sent invoice: {sent['invoice_no']} -> status={sent['status']}")
        return invoice_id
    
    def test_cannot_send_invoice_without_lines(self):
        """Cannot send invoice without lines"""
        token = TestAuth.get_admin_token()
        # Create a draft invoice without lines
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-EMPTY-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": []
            }
        )
        assert create_resp.status_code == 201
        invoice_id = create_resp.json()["id"]
        
        # Try to send
        send_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert send_resp.status_code == 400
        assert "at least one line" in send_resp.json()["detail"]
        print("✓ Correctly blocked sending invoice without lines")
    
    def test_cancel_invoice(self):
        """Cancel sent invoice"""
        token = TestAuth.get_admin_token()
        # Create and send invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-CANCEL-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]
            }
        )
        invoice_id = create_resp.json()["id"]
        
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Cancel it
        cancel_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/cancel",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cancel_resp.status_code == 200
        cancelled = cancel_resp.json()
        assert cancelled["status"] == "Cancelled"
        print(f"✓ Cancelled invoice: {cancelled['invoice_no']}")
    
    def test_delete_draft_invoice(self):
        """Delete draft invoice"""
        token = TestAuth.get_admin_token()
        # Create a draft invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-DELETE-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": []
            }
        )
        invoice_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_resp.status_code == 200
        print(f"✓ Deleted draft invoice: {invoice_id}")
    
    def test_cannot_delete_sent_invoice(self):
        """Cannot delete sent invoice"""
        token = TestAuth.get_admin_token()
        # Create and send invoice
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-NODELETE-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]
            }
        )
        invoice_id = create_resp.json()["id"]
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Try to delete
        delete_resp = requests.delete(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_resp.status_code == 400
        assert "Draft" in delete_resp.json()["detail"]
        print("✓ Correctly blocked deleting sent invoice")


class TestPayments:
    """Payments CRUD"""
    
    def test_list_payments_as_admin(self):
        """Admin can list payments"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payments = response.json()
        assert isinstance(payments, list)
        print(f"✓ Listed {len(payments)} payments")
        for pay in payments[:5]:
            print(f"  - {pay.get('reference', 'N/A')} ({pay['direction']}): {pay['amount']} {pay.get('currency', 'EUR')}")
    
    def test_filter_payments_by_direction(self):
        """Filter payments by direction"""
        token = TestAuth.get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/payments?direction=Inflow",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payments = response.json()
        for pay in payments:
            assert pay["direction"] == "Inflow"
        print(f"✓ Filtered to {len(payments)} Inflow payments")
    
    def test_create_inflow_payment(self):
        """Create inflow payment (money in)"""
        token = TestAuth.get_admin_token()
        
        # Get an account first
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        if not accounts:
            pytest.skip("No accounts available")
        account_id = accounts[0]["id"]
        
        response = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 1000.00,
                "currency": "EUR",
                "date": "2026-01-15",
                "method": "BankTransfer",
                "account_id": account_id,
                "counterparty_name": "TEST Customer",
                "reference": "TEST-PMT-IN-001",
                "note": "Test inflow payment"
            }
        )
        assert response.status_code == 201
        payment = response.json()
        assert payment["direction"] == "Inflow"
        assert payment["amount"] == 1000.00
        assert payment["reference"] == "TEST-PMT-IN-001"
        print(f"✓ Created inflow payment: {payment['reference']}, Amount={payment['amount']} EUR")
        return payment["id"]
    
    def test_create_outflow_payment(self):
        """Create outflow payment (money out)"""
        token = TestAuth.get_admin_token()
        
        # Get an account first
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        if not accounts:
            pytest.skip("No accounts available")
        account_id = accounts[0]["id"]
        
        response = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Outflow",
                "amount": 500.00,
                "currency": "EUR",
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": account_id,
                "counterparty_name": "TEST Supplier",
                "reference": "TEST-PMT-OUT-001",
                "note": "Test outflow payment"
            }
        )
        assert response.status_code == 201
        payment = response.json()
        assert payment["direction"] == "Outflow"
        assert payment["amount"] == 500.00
        print(f"✓ Created outflow payment: {payment['reference']}, Amount={payment['amount']} EUR")
        return payment["id"]
    
    def test_get_payment_details(self):
        """Get payment with allocation details"""
        token = TestAuth.get_admin_token()
        
        # Get any payment
        list_resp = requests.get(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"}
        )
        payments = list_resp.json()
        if not payments:
            pytest.skip("No payments available")
        
        payment_id = payments[0]["id"]
        response = requests.get(
            f"{BASE_URL}/api/finance/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payment = response.json()
        assert "allocations" in payment
        assert "allocated_amount" in payment
        assert "unallocated_amount" in payment
        print(f"✓ Retrieved payment details: {payment.get('reference', payment_id)}, Allocated={payment['allocated_amount']}, Free={payment['unallocated_amount']}")
    
    def test_delete_payment_without_allocations(self):
        """Delete payment without allocations"""
        token = TestAuth.get_admin_token()
        
        # Get an account
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        if not accounts:
            pytest.skip("No accounts available")
        account_id = accounts[0]["id"]
        
        # Create payment
        create_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 100.00,
                "currency": "EUR",
                "date": "2026-01-15",
                "method": "Cash",
                "account_id": account_id,
                "reference": "TEST-TO-DELETE"
            }
        )
        payment_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(
            f"{BASE_URL}/api/finance/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_resp.status_code == 200
        print(f"✓ Deleted payment: {payment_id}")


class TestPaymentAllocation:
    """Payment to Invoice Allocation"""
    
    def test_allocate_payment_to_invoice(self):
        """Allocate inflow payment to issued invoice"""
        token = TestAuth.get_admin_token()
        
        # Get an account
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        if not accounts:
            pytest.skip("No accounts available")
        account_id = accounts[0]["id"]
        
        # Create an issued invoice and send it
        invoice_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-ALLOC-INV-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice_id = invoice_resp.json()["id"]
        invoice_total = invoice_resp.json()["total"]  # 1200 with VAT
        
        # Send the invoice
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Create an inflow payment
        payment_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 600.00,
                "currency": "EUR",
                "date": "2026-01-20",
                "method": "BankTransfer",
                "account_id": account_id,
                "counterparty_name": "Customer",
                "reference": "TEST-PARTIAL-PMT"
            }
        )
        payment_id = payment_resp.json()["id"]
        
        # Allocate payment to invoice
        alloc_resp = requests.post(
            f"{BASE_URL}/api/finance/payments/{payment_id}/allocate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "allocations": [
                    {"invoice_id": invoice_id, "amount": 600.00}
                ]
            }
        )
        assert alloc_resp.status_code == 200
        result = alloc_resp.json()
        assert result["ok"] == True
        assert len(result["allocations"]) == 1
        print(f"✓ Allocated 600 EUR to invoice (Total={invoice_total})")
        
        # Verify invoice status updated to PartiallyPaid
        inv_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        updated_invoice = inv_resp.json()
        assert updated_invoice["status"] == "PartiallyPaid"
        assert updated_invoice["paid_amount"] == 600.00
        assert updated_invoice["remaining_amount"] == invoice_total - 600.00
        print(f"✓ Invoice status updated to PartiallyPaid, Remaining={updated_invoice['remaining_amount']}")
        
        return {"invoice_id": invoice_id, "payment_id": payment_id}
    
    def test_full_payment_updates_to_paid(self):
        """Full payment updates invoice status to Paid"""
        token = TestAuth.get_admin_token()
        
        # Get an account
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        account_id = accounts[0]["id"]
        
        # Create and send invoice (500 + 100 VAT = 600 total)
        invoice_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-FULLPAY-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 500}]
            }
        )
        invoice_id = invoice_resp.json()["id"]
        invoice_total = invoice_resp.json()["total"]  # 600
        
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Create payment for full amount
        payment_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": invoice_total,
                "currency": "EUR",
                "date": "2026-01-20",
                "method": "BankTransfer",
                "account_id": account_id,
                "reference": "TEST-FULL-PMT"
            }
        )
        payment_id = payment_resp.json()["id"]
        
        # Allocate full amount
        alloc_resp = requests.post(
            f"{BASE_URL}/api/finance/payments/{payment_id}/allocate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "allocations": [
                    {"invoice_id": invoice_id, "amount": invoice_total}
                ]
            }
        )
        assert alloc_resp.status_code == 200
        
        # Verify invoice status is Paid
        inv_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        updated_invoice = inv_resp.json()
        assert updated_invoice["status"] == "Paid"
        assert updated_invoice["remaining_amount"] == 0
        print(f"✓ Invoice fully paid, status=Paid, remaining=0")
    
    def test_cannot_allocate_more_than_payment(self):
        """Cannot allocate more than payment amount"""
        token = TestAuth.get_admin_token()
        
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        account_id = accounts[0]["id"]
        
        # Create invoice (total = 1200)
        invoice_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-OVERALLOC-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 1000}]
            }
        )
        invoice_id = invoice_resp.json()["id"]
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Create small payment (100)
        payment_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 100.00,
                "currency": "EUR",
                "date": "2026-01-20",
                "method": "Cash",
                "account_id": account_id,
                "reference": "TEST-SMALL-PMT"
            }
        )
        payment_id = payment_resp.json()["id"]
        
        # Try to allocate more than payment
        alloc_resp = requests.post(
            f"{BASE_URL}/api/finance/payments/{payment_id}/allocate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "allocations": [
                    {"invoice_id": invoice_id, "amount": 500.00}  # Payment is only 100
                ]
            }
        )
        assert alloc_resp.status_code == 400
        assert "exceeds available payment" in alloc_resp.json()["detail"]
        print("✓ Correctly blocked allocation exceeding payment amount")
    
    def test_cannot_allocate_more_than_invoice_remaining(self):
        """Cannot allocate more than invoice remaining"""
        token = TestAuth.get_admin_token()
        
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        account_id = accounts[0]["id"]
        
        # Create small invoice (120 total)
        invoice_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Issued",
                "invoice_no": "TEST-SMALLINV-001",
                "counterparty_name": "Customer",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Service", "qty": 1, "unit_price": 100}]
            }
        )
        invoice_id = invoice_resp.json()["id"]
        invoice_total = invoice_resp.json()["total"]  # 120
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Create large payment (1000)
        payment_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 1000.00,
                "currency": "EUR",
                "date": "2026-01-20",
                "method": "BankTransfer",
                "account_id": account_id,
                "reference": "TEST-LARGE-PMT"
            }
        )
        payment_id = payment_resp.json()["id"]
        
        # Try to allocate more than invoice remaining
        alloc_resp = requests.post(
            f"{BASE_URL}/api/finance/payments/{payment_id}/allocate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "allocations": [
                    {"invoice_id": invoice_id, "amount": 500.00}  # Invoice total is only 120
                ]
            }
        )
        assert alloc_resp.status_code == 400
        assert "exceeds invoice remaining" in alloc_resp.json()["detail"]
        print("✓ Correctly blocked allocation exceeding invoice remaining")
    
    def test_direction_mismatch_blocked(self):
        """Cannot allocate inflow to received invoice"""
        token = TestAuth.get_admin_token()
        
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        account_id = accounts[0]["id"]
        
        # Create RECEIVED invoice (bill)
        invoice_resp = requests.post(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Received",
                "invoice_no": "TEST-MISMATCH-001",
                "counterparty_name": "Supplier",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
                "currency": "EUR",
                "vat_percent": 20.0,
                "lines": [{"description": "Materials", "qty": 1, "unit_price": 100}]
            }
        )
        invoice_id = invoice_resp.json()["id"]
        requests.post(
            f"{BASE_URL}/api/finance/invoices/{invoice_id}/send",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Create INFLOW payment (should match Issued invoices, not Received)
        payment_resp = requests.post(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "direction": "Inflow",
                "amount": 500.00,
                "currency": "EUR",
                "date": "2026-01-20",
                "method": "Cash",
                "account_id": account_id,
                "reference": "TEST-MISMATCH-PMT"
            }
        )
        payment_id = payment_resp.json()["id"]
        
        # Try to allocate inflow to received invoice
        alloc_resp = requests.post(
            f"{BASE_URL}/api/finance/payments/{payment_id}/allocate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "allocations": [
                    {"invoice_id": invoice_id, "amount": 100.00}
                ]
            }
        )
        assert alloc_resp.status_code == 400
        assert "direction doesn't match" in alloc_resp.json()["detail"]
        print("✓ Correctly blocked direction mismatch (Inflow -> Received)")


class TestFinanceEnums:
    """Finance enums endpoint"""
    
    def test_get_finance_enums(self):
        """Get all finance enums"""
        response = requests.get(f"{BASE_URL}/api/finance/enums")
        assert response.status_code == 200
        data = response.json()
        assert "account_types" in data
        assert "invoice_directions" in data
        assert "invoice_statuses" in data
        assert "payment_directions" in data
        assert "cost_categories" in data
        assert "Cash" in data["account_types"]
        assert "Bank" in data["account_types"]
        assert "Issued" in data["invoice_directions"]
        assert "Received" in data["invoice_directions"]
        print(f"✓ Finance enums retrieved: {list(data.keys())}")


class TestCleanup:
    """Cleanup TEST_ prefixed data"""
    
    def test_cleanup_test_data(self):
        """Remove all TEST_ prefixed test data"""
        token = TestAuth.get_admin_token()
        
        # Cleanup invoices
        invoices_resp = requests.get(
            f"{BASE_URL}/api/finance/invoices",
            headers={"Authorization": f"Bearer {token}"}
        )
        invoices = invoices_resp.json()
        deleted_invoices = 0
        for inv in invoices:
            if inv.get("invoice_no", "").startswith("TEST-"):
                # For non-draft, cancel first
                if inv["status"] != "Draft":
                    requests.post(
                        f"{BASE_URL}/api/finance/invoices/{inv['id']}/cancel",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                # Then delete (may fail if not Draft anymore, that's ok)
                requests.delete(
                    f"{BASE_URL}/api/finance/invoices/{inv['id']}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                deleted_invoices += 1
        
        # Cleanup payments (those without allocations)
        payments_resp = requests.get(
            f"{BASE_URL}/api/finance/payments",
            headers={"Authorization": f"Bearer {token}"}
        )
        payments = payments_resp.json()
        deleted_payments = 0
        for pay in payments:
            if pay.get("reference", "").startswith("TEST-"):
                if pay.get("allocation_count", 0) == 0:
                    requests.delete(
                        f"{BASE_URL}/api/finance/payments/{pay['id']}",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    deleted_payments += 1
        
        # Cleanup accounts
        accounts_resp = requests.get(
            f"{BASE_URL}/api/finance/accounts",
            headers={"Authorization": f"Bearer {token}"}
        )
        accounts = accounts_resp.json()
        deleted_accounts = 0
        for acc in accounts:
            if acc.get("name", "").startswith("TEST_"):
                result = requests.delete(
                    f"{BASE_URL}/api/finance/accounts/{acc['id']}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if result.status_code == 200:
                    deleted_accounts += 1
        
        print(f"✓ Cleanup complete: {deleted_invoices} invoices, {deleted_payments} payments, {deleted_accounts} accounts")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
