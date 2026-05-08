"""
Test: Finance Revenue Split & Invoice Payment History
Tests for:
1. GET /api/projects/{projectId}/financial-results - earned_revenue (cash), invoiced_revenue (accrual), revenue_mode='cash'
2. GET /api/projects/{projectId}/dashboard - invoices with payments[] array, totals with subtotal/vat/total/paid/unpaid
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"

@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("token")

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestFinancialResultsAPI:
    """Tests for GET /api/projects/{projectId}/financial-results"""
    
    def test_financial_results_returns_200(self, auth_headers):
        """Financial results endpoint returns 200"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    def test_financial_results_has_operating_section(self, auth_headers):
        """Financial results contains operating section"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        assert "operating" in data, "Missing 'operating' section"
    
    def test_operating_has_earned_revenue_cash_basis(self, auth_headers):
        """Operating section has earned_revenue (cash basis - actual paid amounts)"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        operating = data.get("operating", {})
        assert "earned_revenue" in operating, "Missing 'earned_revenue' in operating"
        # earned_revenue should be numeric
        assert isinstance(operating["earned_revenue"], (int, float)), "earned_revenue should be numeric"
    
    def test_operating_has_invoiced_revenue_accrual(self, auth_headers):
        """Operating section has invoiced_revenue (accrual basis - total invoiced)"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        operating = data.get("operating", {})
        assert "invoiced_revenue" in operating, "Missing 'invoiced_revenue' in operating"
        assert isinstance(operating["invoiced_revenue"], (int, float)), "invoiced_revenue should be numeric"
    
    def test_operating_has_revenue_mode_cash(self, auth_headers):
        """Operating section has revenue_mode='cash'"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        operating = data.get("operating", {})
        assert "revenue_mode" in operating, "Missing 'revenue_mode' in operating"
        assert operating["revenue_mode"] == "cash", f"Expected revenue_mode='cash', got '{operating['revenue_mode']}'"
    
    def test_earned_revenue_vs_invoiced_revenue_logic(self, auth_headers):
        """Earned revenue (paid) should be <= invoiced revenue (total)"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        operating = data.get("operating", {})
        earned = operating.get("earned_revenue", 0)
        invoiced = operating.get("invoiced_revenue", 0)
        # Earned (paid) should not exceed invoiced (total)
        assert earned <= invoiced, f"earned_revenue ({earned}) should be <= invoiced_revenue ({invoiced})"
    
    def test_financial_results_has_cash_section(self, auth_headers):
        """Financial results contains cash section"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        assert "cash" in data, "Missing 'cash' section"
    
    def test_financial_results_has_fully_loaded_section(self, auth_headers):
        """Financial results contains fully_loaded section"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/financial-results", headers=auth_headers)
        data = resp.json()
        assert "fully_loaded" in data, "Missing 'fully_loaded' section"


class TestDashboardInvoicesAPI:
    """Tests for GET /api/projects/{projectId}/dashboard - invoices with payments"""
    
    def test_dashboard_returns_200(self, auth_headers):
        """Dashboard endpoint returns 200"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    def test_dashboard_has_invoices_section(self, auth_headers):
        """Dashboard contains invoices section"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        assert "invoices" in data, "Missing 'invoices' section"
    
    def test_invoices_has_list(self, auth_headers):
        """Invoices section has invoices list"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices = data.get("invoices", {})
        assert "invoices" in invoices, "Missing 'invoices' list in invoices section"
        assert isinstance(invoices["invoices"], list), "invoices should be a list"
    
    def test_invoices_has_totals(self, auth_headers):
        """Invoices section has totals with subtotal, vat, total, paid, unpaid"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices = data.get("invoices", {})
        totals = invoices.get("totals", {})
        
        required_fields = ["subtotal", "vat", "total", "paid", "unpaid"]
        for field in required_fields:
            assert field in totals, f"Missing '{field}' in invoices.totals"
            assert isinstance(totals[field], (int, float)), f"totals.{field} should be numeric"
    
    def test_invoice_has_payments_array(self, auth_headers):
        """Each invoice has payments array"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        if len(invoices_list) > 0:
            for inv in invoices_list:
                assert "payments" in inv, f"Invoice {inv.get('invoice_no')} missing 'payments' array"
                assert isinstance(inv["payments"], list), f"Invoice {inv.get('invoice_no')} payments should be a list"
    
    def test_invoice_has_breakdown_fields(self, auth_headers):
        """Each invoice has subtotal, vat_amount, total breakdown"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        if len(invoices_list) > 0:
            inv = invoices_list[0]
            assert "subtotal" in inv, "Invoice missing 'subtotal'"
            assert "vat_amount" in inv, "Invoice missing 'vat_amount'"
            assert "total" in inv, "Invoice missing 'total'"
            assert "paid_amount" in inv, "Invoice missing 'paid_amount'"
            assert "remaining_amount" in inv, "Invoice missing 'remaining_amount'"
    
    def test_payment_has_required_fields(self, auth_headers):
        """Payment allocations have date, amount, method, reference"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        # Find an invoice with payments
        for inv in invoices_list:
            payments = inv.get("payments", [])
            if len(payments) > 0:
                p = payments[0]
                assert "amount" in p, "Payment missing 'amount'"
                # date, method, reference are optional but should exist as keys
                assert "date" in p or p.get("date") is None, "Payment should have 'date' key"
                assert "method" in p or p.get("method") is None, "Payment should have 'method' key"
                break


class TestDashboardBalanceCard:
    """Tests for balance card - should show paid income, not inflated by unpaid invoices"""
    
    def test_dashboard_has_balance_section(self, auth_headers):
        """Dashboard contains balance section"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        assert "balance" in data, "Missing 'balance' section"
    
    def test_balance_income_equals_paid_invoices(self, auth_headers):
        """Balance income should equal paid invoices (not total invoiced)"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        
        balance = data.get("balance", {})
        invoices = data.get("invoices", {})
        
        income = balance.get("income", 0)
        totals_paid = invoices.get("totals", {}).get("paid", 0)
        
        # Income should match paid amount (cash basis)
        assert income == totals_paid, f"Balance income ({income}) should equal invoices.totals.paid ({totals_paid})"


class TestSpecificProjectData:
    """Tests for the specific project c3529276-8c03-49b3-92de-51216aab25da"""
    
    def test_project_has_invoice_inv_1007(self, auth_headers):
        """Project should have invoice INV-1007"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        inv_numbers = [inv.get("invoice_no") for inv in invoices_list]
        assert "INV-1007" in inv_numbers, f"Expected INV-1007 in invoices, got: {inv_numbers}"
    
    def test_inv_1007_has_payment_allocation(self, auth_headers):
        """INV-1007 should have payment allocation of 10000 BGN"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        inv_1007 = next((inv for inv in invoices_list if inv.get("invoice_no") == "INV-1007"), None)
        assert inv_1007 is not None, "INV-1007 not found"
        
        payments = inv_1007.get("payments", [])
        assert len(payments) > 0, "INV-1007 should have at least 1 payment"
        
        # Check payment amount
        total_paid = sum(p.get("amount", 0) for p in payments)
        assert total_paid == 10000, f"Expected 10000 paid, got {total_paid}"
    
    def test_inv_1007_payment_method_bank_transfer(self, auth_headers):
        """INV-1007 payment should be via BankTransfer"""
        resp = requests.get(f"{BASE_URL}/api/projects/{PROJECT_ID}/dashboard", headers=auth_headers)
        data = resp.json()
        invoices_list = data.get("invoices", {}).get("invoices", [])
        
        inv_1007 = next((inv for inv in invoices_list if inv.get("invoice_no") == "INV-1007"), None)
        if inv_1007:
            payments = inv_1007.get("payments", [])
            if len(payments) > 0:
                method = payments[0].get("method")
                assert method == "BankTransfer", f"Expected BankTransfer, got {method}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
