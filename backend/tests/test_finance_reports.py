"""
Tests for Finance Reports endpoints.
Tests turnover-by-client and company-finance-summary APIs.
"""
import pytest
import requests
import os

from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD


def get_admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


class TestTurnoverByClient:
    """Test Turnover by Client endpoint"""

    def test_turnover_by_client_format(self):
        """Test turnover-by-client endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/turnover-by-client",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "grand_totals" in data, "Missing 'grand_totals' in response"
        assert "filters" in data, "Missing 'filters' in response"
        
        # Check grand_totals structure
        gt = data["grand_totals"]
        assert "total_invoices" in gt
        assert "total_subtotal" in gt
        assert "total_vat" in gt
        assert "total_amount" in gt
        print(f"✓ Turnover by client: total={data['total']}, grand_total={gt['total_amount']}")

    def test_turnover_by_client_date_filter(self):
        """Test date filtering for turnover by client"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/turnover-by-client?date_from=2025-01-01&date_to=2025-12-31",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filters"]["date_from"] == "2025-01-01"
        assert data["filters"]["date_to"] == "2025-12-31"
        print(f"✓ Date filter works: from={data['filters']['date_from']}, to={data['filters']['date_to']}")


class TestCompanyFinanceSummary:
    """Test Company Finance Summary endpoint"""

    def test_finance_summary_format(self):
        """Test company-finance-summary endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-summary?year=2026&month=1",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "year" in data, "Missing 'year' in response"
        assert "month" in data, "Missing 'month' in response"
        assert "weeks" in data, "Missing 'weeks' in response"
        assert "totals" in data, "Missing 'totals' in response"
        assert "income_breakdown" in data, "Missing 'income_breakdown' in response"
        assert "expense_breakdown" in data, "Missing 'expense_breakdown' in response"
        assert "cumulative_balance" in data, "Missing 'cumulative_balance' in response"
        
        # Check totals structure
        totals = data["totals"]
        assert "income" in totals
        assert "expenses" in totals
        assert "net_balance" in totals
        
        # Verify net_balance calculation
        assert totals["net_balance"] == round(totals["income"] - totals["expenses"], 2)
        
        print(f"✓ Finance summary: year={data['year']}, month={data['month']}")
        print(f"  Income: {totals['income']}, Expenses: {totals['expenses']}, Net: {totals['net_balance']}")

    def test_finance_summary_weekly_data(self):
        """Test that weekly data structure is correct"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-summary?year=2026&month=1",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        weeks = data["weeks"]
        assert len(weeks) >= 4, "Should have at least 4 weeks in January"
        
        for week in weeks:
            assert "week" in week
            assert "label" in week
            assert "income" in week
            assert "expenses" in week
            assert "income_invoices" in week
            assert "income_cash" in week
            assert "expenses_invoices" in week
            assert "expenses_cash" in week
            assert "expenses_overhead" in week
            assert "expenses_payroll" in week
            assert "expenses_bonus" in week
        
        print(f"✓ Weekly data structure verified: {len(weeks)} weeks")

    def test_finance_summary_cumulative_balance(self):
        """Test cumulative balance calculation"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-summary?year=2026&month=1",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        cumulative = data["cumulative_balance"]
        weeks = data["weeks"]
        
        # Verify cumulative balance matches weekly calculations
        running_balance = 0
        for i, week in enumerate(weeks):
            running_balance += week["income"] - week["expenses"]
            expected_balance = round(running_balance, 2)
            assert cumulative[i]["balance"] == expected_balance, \
                f"Week {i+1}: expected {expected_balance}, got {cumulative[i]['balance']}"
        
        print(f"✓ Cumulative balance calculation verified")

    def test_finance_summary_invalid_month(self):
        """Test invalid month parameter"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-summary?year=2026&month=13",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 422, "Should reject month > 12"
        print(f"✓ Invalid month (13) correctly rejected")


class TestFinanceCompare:
    """Test Finance Compare (3 Months) endpoints"""

    def test_compare_with_months_param(self):
        """Test compare endpoint with year and months parameters"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-compare?year=2026&months=01,02,03",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "months" in data
        assert "bar_chart_data" in data
        assert "line_chart_data" in data
        assert "overall_totals" in data
        
        # Should have 3 months
        assert len(data["months"]) == 3
        
        # Check month structure
        for m in data["months"]:
            assert "year" in m
            assert "month" in m
            assert "month_name" in m
            assert "totals" in m
            assert "income_total" in m["totals"]
            assert "expenses_total" in m["totals"]
            assert "net" in m["totals"]
            assert "expense_breakdown" in m
            assert "top_expense_type" in m
        
        print(f"✓ Compare with months param: {len(data['months'])} months returned")

    def test_compare_last3_mode(self):
        """Test compare endpoint with mode=last3"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-compare?mode=last3",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should have 3 months
        assert len(data["months"]) == 3
        
        # Months should be in chronological order
        months = data["months"]
        for i in range(len(months) - 1):
            curr_date = months[i]["year"] * 12 + months[i]["month"]
            next_date = months[i+1]["year"] * 12 + months[i+1]["month"]
            assert curr_date < next_date, "Months should be in chronological order"
        
        # Check overall totals structure
        totals = data["overall_totals"]
        assert "income" in totals
        assert "expenses" in totals
        assert "net" in totals
        
        print(f"✓ Compare last3 mode: returned {[m['month_name'] for m in data['months']]}")

    def test_compare_invalid_params(self):
        """Test compare endpoint with missing parameters"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-compare",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 422
        print(f"✓ Missing params correctly rejected")

    def test_compare_chart_data_format(self):
        """Test that chart data is properly formatted"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-compare?year=2026&months=01,02,03",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Bar chart data
        bar_data = data["bar_chart_data"]
        assert len(bar_data) == 3
        for item in bar_data:
            assert "month" in item
            assert "month_full" in item
            assert "income" in item
            assert "expenses" in item
        
        # Line chart data
        line_data = data["line_chart_data"]
        assert len(line_data) == 3
        for item in line_data:
            assert "month" in item
            assert "net" in item
        
        print(f"✓ Chart data format verified")


class TestCashTransactions:
    """Test Cash Transactions CRUD"""

    def test_list_cash_transactions(self):
        """Test listing cash transactions"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/cash-transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        print(f"✓ Cash transactions: total={data['total']}")

    def test_create_cash_transaction(self):
        """Test creating a cash transaction"""
        token = get_admin_token()
        txn_data = {
            "date": "2026-01-15",
            "type": "income",
            "amount": 1500.00,
            "category": "Услуги",
            "description": "Test cash income"
        }
        response = requests.post(
            f"{BASE_URL}/api/finance/cash-transactions",
            json=txn_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "income"
        assert data["amount"] == 1500.00
        assert "id" in data
        print(f"✓ Created cash transaction: id={data['id']}, amount={data['amount']}")


class TestOverheadTransactions:
    """Test Overhead Transactions CRUD"""

    def test_list_overhead_transactions(self):
        """Test listing overhead transactions"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/overhead-transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        print(f"✓ Overhead transactions: total={data['total']}")

    def test_create_overhead_transaction(self):
        """Test creating an overhead transaction"""
        token = get_admin_token()
        txn_data = {
            "date": "2026-01-10",
            "amount": 800.00,
            "category": "Наем офис",
            "description": "Test overhead"
        }
        response = requests.post(
            f"{BASE_URL}/api/finance/overhead-transactions",
            json=txn_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["amount"] == 800.00
        assert "id" in data
        print(f"✓ Created overhead transaction: id={data['id']}, amount={data['amount']}")


class TestBonusPayments:
    """Test Bonus Payments CRUD"""

    def test_list_bonus_payments(self):
        """Test listing bonus payments"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/finance/bonus-payments",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        print(f"✓ Bonus payments: total={data['total']}")

    def test_create_bonus_payment(self):
        """Test creating a bonus payment"""
        token = get_admin_token()
        payment_data = {
            "date": "2026-01-25",
            "amount": 1000.00,
            "description": "Test bonus"
        }
        response = requests.post(
            f"{BASE_URL}/api/finance/bonus-payments",
            json=payment_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["amount"] == 1000.00
        assert "id" in data
        print(f"✓ Created bonus payment: id={data['id']}, amount={data['amount']}")
