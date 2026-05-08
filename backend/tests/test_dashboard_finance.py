"""
Tests for Dashboard Activity and Finance Details endpoints.
"""
import pytest
import requests
import os

from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

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


class TestDashboardActivity:
    """Test Dashboard Activity endpoint"""

    def test_activity_list_format(self):
        """Test activity endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/dashboard/activity?limit=10",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        
        print(f"✓ Activity list: total={data['total']}, items={len(data['items'])}")

    def test_activity_pagination(self):
        """Test activity pagination works"""
        token = get_admin_token()
        
        response1 = requests.get(
            f"{BASE_URL}/api/dashboard/activity?limit=5&page=1",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        
        response2 = requests.get(
            f"{BASE_URL}/api/dashboard/activity?limit=5&page=2",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Different pages should have different data (if enough items)
        if data1["total"] > 5:
            assert data2["page"] == 2
        
        print(f"✓ Activity pagination works")


class TestFinanceSeries:
    """Test Finance Series (rolling N months) endpoint"""

    def test_finance_series_format(self):
        """Test finance series endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-series?months=3",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "months" in data
        assert "period_months" in data
        assert "totals" in data
        
        assert data["period_months"] == 3
        assert len(data["months"]) == 3
        
        # Check month structure
        for m in data["months"]:
            assert "year" in m
            assert "month" in m
            assert "month_name" in m
            assert "income_total" in m
            assert "expenses_total" in m
            assert "net" in m
            assert "breakdown" in m
        
        print(f"✓ Finance series: {len(data['months'])} months, total income={data['totals']['income']}")

    def test_finance_series_different_periods(self):
        """Test finance series with different period lengths"""
        token = get_admin_token()
        
        for months in [1, 6, 12]:
            response = requests.get(
                f"{BASE_URL}/api/reports/company-finance-series?months={months}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["months"]) == months
        
        print(f"✓ Different period lengths work correctly")


class TestFinanceDetailsSummary:
    """Test Finance Details Summary endpoint"""

    def test_summary_format(self):
        """Test finance details summary returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/finance-details/summary?preset=last_3_months",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "period" in data
        assert "totals" in data
        assert "breakdown" in data
        assert "counts" in data
        assert "kpis" in data
        
        # Check totals
        assert "income" in data["totals"]
        assert "expenses" in data["totals"]
        assert "net" in data["totals"]
        
        # Check breakdown
        assert "income_invoices" in data["breakdown"]
        assert "expenses_invoices" in data["breakdown"]
        assert "expenses_overhead" in data["breakdown"]
        
        # Check KPIs
        assert "avg_weekly_income" in data["kpis"]
        assert "avg_weekly_expenses" in data["kpis"]
        
        print(f"✓ Summary format: income={data['totals']['income']}, expenses={data['totals']['expenses']}")

    def test_summary_presets(self):
        """Test different preset filters"""
        token = get_admin_token()
        
        presets = ["this_month", "last_month", "last_3_months", "last_6_months", "last_12_months", "this_year"]
        
        for preset in presets:
            response = requests.get(
                f"{BASE_URL}/api/reports/finance-details/summary?preset={preset}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "period" in data
            assert data["period"]["date_from"] is not None
            assert data["period"]["date_to"] is not None
        
        print(f"✓ All presets work correctly")


class TestFinanceDetailsByCounterparty:
    """Test Finance Details By Counterparty endpoint"""

    def test_by_counterparty_format(self):
        """Test by counterparty endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/finance-details/by-counterparty?preset=last_3_months",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "period" in data
        
        for item in data["items"]:
            assert "counterparty_id" in item
            assert "counterparty_name" in item
            assert "total_income" in item
            assert "total_expenses" in item
        
        print(f"✓ By counterparty: {data['total']} counterparties")


class TestFinanceDetailsByProject:
    """Test Finance Details By Project endpoint"""

    def test_by_project_format(self):
        """Test by project endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/finance-details/by-project?preset=last_3_months",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "page" in data
        
        print(f"✓ By project: {data['total']} projects")


class TestFinanceDetailsTransactions:
    """Test Finance Details Transactions endpoint"""

    def test_transactions_format(self):
        """Test transactions endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/finance-details/transactions?preset=last_3_months",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "page" in data
        
        for item in data["items"]:
            assert "type" in item
            assert "date" in item
            assert "direction" in item
            assert "amount" in item
        
        print(f"✓ Transactions: {data['total']} total")

    def test_transactions_filter_by_type(self):
        """Test filtering transactions by type"""
        token = get_admin_token()
        
        for txn_type in ["invoice", "cash", "overhead", "payroll", "bonus"]:
            response = requests.get(
                f"{BASE_URL}/api/reports/finance-details/transactions?preset=last_3_months&transaction_type={txn_type}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            # All returned items should be of the specified type
            for item in data["items"]:
                assert item["type"] == txn_type
        
        print(f"✓ Transaction type filters work correctly")


class TestTopCounterparties:
    """Test Top Counterparties endpoint"""

    def test_top_counterparties_format(self):
        """Test top counterparties endpoint returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/finance-details/top-counterparties?preset=last_3_months",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "direction" in data
        
        for item in data["items"]:
            assert "counterparty_id" in item
            assert "counterparty_name" in item
            assert "total" in item
            assert "invoice_count" in item
        
        print(f"✓ Top counterparties: {len(data['items'])} items")
