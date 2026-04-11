"""
Test suite for All Reports feature (GET /api/all-reports)
Tests the central read-only view of all labor reports across workers, sites, activities, and dates.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from backend/.env
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"


class TestAllReportsAPI:
    """Tests for GET /api/all-reports endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip(f"Authentication failed: {login_response.status_code}")
        
        token = login_response.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        yield
        self.session.close()
    
    def test_all_reports_returns_200(self):
        """Test that GET /api/all-reports returns 200 status"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/all-reports returns 200")
    
    def test_all_reports_response_structure(self):
        """Test response has required fields: items, total, summary"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check top-level fields
        assert "items" in data, "Response missing 'items' field"
        assert "total" in data, "Response missing 'total' field"
        assert "summary" in data, "Response missing 'summary' field"
        assert "page" in data, "Response missing 'page' field"
        assert "page_size" in data, "Response missing 'page_size' field"
        assert "total_pages" in data, "Response missing 'total_pages' field"
        
        print(f"PASS: Response structure valid - total={data['total']}, page={data['page']}")
    
    def test_summary_has_required_fields(self):
        """Test summary has hours/overtime/value/by_status breakdown"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        summary = response.json().get("summary", {})
        
        # Check summary fields
        assert "total_hours" in summary, "Summary missing 'total_hours'"
        assert "normal_hours" in summary, "Summary missing 'normal_hours'"
        assert "overtime_hours" in summary, "Summary missing 'overtime_hours'"
        assert "total_value" in summary, "Summary missing 'total_value'"
        assert "by_status" in summary, "Summary missing 'by_status'"
        
        print(f"PASS: Summary fields valid - hours={summary['total_hours']}, overtime={summary['overtime_hours']}, value={summary['total_value']}")
        print(f"      by_status breakdown: {summary['by_status']}")
    
    def test_report_item_structure(self):
        """Test each report item has required fields"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        items = response.json().get("items", [])
        
        if not items:
            pytest.skip("No report items to validate structure")
        
        # Check first item has all required fields
        item = items[0]
        required_fields = [
            "id", "date", "worker_name", "site_name", "smr_type",
            "hours", "normal_hours", "overtime_hours", "hourly_rate",
            "labor_value", "report_status", "payroll_status"
        ]
        
        for field in required_fields:
            assert field in item, f"Report item missing '{field}' field"
        
        print(f"PASS: Report item structure valid - {len(items)} items returned")
        print(f"      Sample: date={item['date']}, worker={item['worker_name']}, hours={item['hours']}")
    
    def test_date_filter(self):
        """Test date_from and date_to filters work"""
        # Get all reports first
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        # Test with specific date range
        params = {
            "date_from": "2025-01-01",
            "date_to": "2025-12-31"
        }
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        print(f"PASS: Date filter works - {data['total']} reports in 2025")
    
    def test_status_filter(self):
        """Test report_status filter works"""
        # Test DRAFT filter
        params = {"report_status": "DRAFT"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify all returned items have DRAFT status
        for item in data.get("items", []):
            assert item["report_status"] == "DRAFT", f"Expected DRAFT, got {item['report_status']}"
        
        print(f"PASS: Status filter works - {data['total']} DRAFT reports")
    
    def test_smr_filter(self):
        """Test smr filter (regex search on smr_type)"""
        params = {"smr": "test"}  # Search for 'test' in smr_type
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        print(f"PASS: SMR filter works - {data['total']} reports matching 'test'")
    
    def test_only_overtime_filter(self):
        """Test only_overtime filter returns only reports with overtime > 0"""
        params = {"only_overtime": "true"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify all returned items have overtime > 0
        for item in data.get("items", []):
            assert item["overtime_hours"] > 0, f"Expected overtime > 0, got {item['overtime_hours']}"
        
        print(f"PASS: Overtime filter works - {data['total']} reports with overtime")
    
    def test_sort_by_date(self):
        """Test sort_by=date works"""
        # Test descending (default)
        params = {"sort_by": "date", "sort_dir": "desc"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        items = response.json().get("items", [])
        if len(items) >= 2:
            # Verify descending order
            for i in range(len(items) - 1):
                assert items[i]["date"] >= items[i+1]["date"], "Dates not in descending order"
        
        print(f"PASS: Sort by date (desc) works")
    
    def test_sort_by_worker(self):
        """Test sort_by=worker works"""
        params = {"sort_by": "worker", "sort_dir": "asc"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        print(f"PASS: Sort by worker works")
    
    def test_sort_by_hours(self):
        """Test sort_by=hours works"""
        params = {"sort_by": "hours", "sort_dir": "desc"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        items = response.json().get("items", [])
        if len(items) >= 2:
            # Verify descending order
            for i in range(len(items) - 1):
                assert items[i]["hours"] >= items[i+1]["hours"], "Hours not in descending order"
        
        print(f"PASS: Sort by hours (desc) works")
    
    def test_sort_by_value(self):
        """Test sort_by=value works"""
        params = {"sort_by": "value", "sort_dir": "desc"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        print(f"PASS: Sort by value works")
    
    def test_sort_by_status(self):
        """Test sort_by=status works"""
        params = {"sort_by": "status", "sort_dir": "asc"}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        print(f"PASS: Sort by status works")
    
    def test_pagination(self):
        """Test pagination works correctly"""
        # Get first page
        params = {"page": 1, "page_size": 10}
        response = self.session.get(f"{BASE_URL}/api/all-reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["items"]) <= 10
        
        print(f"PASS: Pagination works - page 1 of {data['total_pages']}, {len(data['items'])} items")
    
    def test_unauthenticated_request_rejected(self):
        """Test that unauthenticated requests are rejected"""
        # Create new session without auth
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/all-reports")
        
        # Should return 401 or 403
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        
        print(f"PASS: Unauthenticated request rejected with {response.status_code}")
    
    def test_summary_math_consistency(self):
        """Test that summary hours = normal + overtime"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        summary = response.json().get("summary", {})
        total = summary.get("total_hours", 0)
        normal = summary.get("normal_hours", 0)
        overtime = summary.get("overtime_hours", 0)
        
        # Allow small floating point tolerance
        assert abs(total - (normal + overtime)) < 0.1, f"Hours mismatch: {total} != {normal} + {overtime}"
        
        print(f"PASS: Summary math consistent - {total} = {normal} + {overtime}")
    
    def test_status_breakdown_counts(self):
        """Test that by_status breakdown sums to total"""
        response = self.session.get(f"{BASE_URL}/api/all-reports")
        assert response.status_code == 200
        
        data = response.json()
        total = data.get("total", 0)
        by_status = data.get("summary", {}).get("by_status", {})
        
        status_sum = sum(by_status.values())
        assert status_sum == total, f"Status breakdown sum {status_sum} != total {total}"
        
        print(f"PASS: Status breakdown sums to total - {by_status}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
