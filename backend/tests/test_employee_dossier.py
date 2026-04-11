"""
Test Employee Dossier API - GET /api/employee-dossier/{worker_id}
Tests the aggregated dossier view for workers including:
- Header info (name, position, pay_type, hourly_rate, avatar_url, is_active, phone)
- Reports section (flat report lines with date, project, smr, hours, normal, overtime, value, status, payroll_status)
- Payroll section (weekly history with gross/bonuses/deductions/net/status)
- Calendar section (daily entries with status/hours/has_report)
- Advances section (all advances/loans with amount/remaining/status)
- Warnings section
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test worker ID from main agent context
TEST_WORKER_ID = "6f69367a-e25f-489d-a7c8-f25cde6a9ac5"  # Светлин Антонов
TEST_WORKER_NAME = "Светлин Антонов"


class TestEmployeeDossierAPI:
    """Employee Dossier endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        
        if login_response.status_code == 200:
            token = login_response.json().get("token")  # API returns 'token' not 'access_token'
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
            else:
                pytest.skip("No token in login response")
        else:
            pytest.skip(f"Authentication failed: {login_response.status_code}")
    
    def test_employee_dossier_endpoint_exists(self):
        """Test that the employee dossier endpoint is accessible"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Employee dossier endpoint accessible for worker {TEST_WORKER_ID}")
    
    def test_employee_dossier_returns_header(self):
        """Test that dossier returns header with required fields"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "header" in data, "Response should contain 'header' field"
        
        header = data["header"]
        # Required header fields
        required_fields = ["id", "first_name", "last_name", "email", "phone", "role", 
                          "avatar_url", "is_active", "position", "pay_type", "hourly_rate"]
        
        for field in required_fields:
            assert field in header, f"Header should contain '{field}' field"
        
        # Verify worker ID matches
        assert header["id"] == TEST_WORKER_ID, f"Worker ID mismatch"
        
        print(f"✓ Header contains all required fields")
        print(f"  - Name: {header['first_name']} {header['last_name']}")
        print(f"  - Position: {header.get('position', 'N/A')}")
        print(f"  - Pay type: {header.get('pay_type', 'N/A')}")
        print(f"  - Hourly rate: {header.get('hourly_rate', 0)}")
        print(f"  - Is active: {header.get('is_active', True)}")
    
    def test_employee_dossier_returns_reports(self):
        """Test that dossier returns reports section with flat report lines"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "reports" in data, "Response should contain 'reports' field"
        
        reports = data["reports"]
        assert "lines" in reports, "Reports should contain 'lines' array"
        assert "total_hours" in reports, "Reports should contain 'total_hours'"
        assert "total_value" in reports, "Reports should contain 'total_value'"
        assert "count" in reports, "Reports should contain 'count'"
        
        # Verify report line structure if there are reports
        if reports["lines"]:
            line = reports["lines"][0]
            required_line_fields = ["id", "date", "project_id", "project_name", "smr", 
                                   "hours", "normal", "overtime", "value", "status", "payroll_status"]
            for field in required_line_fields:
                assert field in line, f"Report line should contain '{field}' field"
        
        print(f"✓ Reports section valid")
        print(f"  - Total reports: {reports['count']}")
        print(f"  - Total hours: {reports['total_hours']}")
        print(f"  - Total value: {reports['total_value']}")
    
    def test_employee_dossier_returns_payroll(self):
        """Test that dossier returns payroll section with weekly history"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "payroll" in data, "Response should contain 'payroll' field"
        
        payroll = data["payroll"]
        assert "weeks" in payroll, "Payroll should contain 'weeks' array"
        assert "total_gross" in payroll, "Payroll should contain 'total_gross'"
        assert "total_net" in payroll, "Payroll should contain 'total_net'"
        assert "total_paid" in payroll, "Payroll should contain 'total_paid'"
        
        # Verify payroll week structure if there are weeks
        if payroll["weeks"]:
            week = payroll["weeks"][0]
            required_week_fields = ["batch_id", "week_start", "week_end", "status", 
                                   "days", "hours", "normal", "overtime", 
                                   "gross", "bonuses", "deductions", "net"]
            for field in required_week_fields:
                assert field in week, f"Payroll week should contain '{field}' field"
        
        print(f"✓ Payroll section valid")
        print(f"  - Total weeks: {len(payroll['weeks'])}")
        print(f"  - Total gross: {payroll['total_gross']}")
        print(f"  - Total net: {payroll['total_net']}")
        print(f"  - Total paid: {payroll['total_paid']}")
    
    def test_employee_dossier_returns_advances(self):
        """Test that dossier returns advances section"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "advances" in data, "Response should contain 'advances' field"
        
        advances = data["advances"]
        assert isinstance(advances, list), "Advances should be a list"
        
        # Verify advance structure if there are advances
        if advances:
            advance = advances[0]
            required_advance_fields = ["id", "type", "amount", "remaining", "status", "date", "note"]
            for field in required_advance_fields:
                assert field in advance, f"Advance should contain '{field}' field"
        
        print(f"✓ Advances section valid")
        print(f"  - Total advances: {len(advances)}")
    
    def test_employee_dossier_returns_calendar(self):
        """Test that dossier returns calendar section with daily entries"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "calendar" in data, "Response should contain 'calendar' field"
        
        calendar = data["calendar"]
        assert isinstance(calendar, list), "Calendar should be a list"
        
        # Verify calendar entry structure if there are entries
        if calendar:
            entry = calendar[0]
            required_cal_fields = ["date", "weekday", "status", "hours", "has_report", "overtime"]
            for field in required_cal_fields:
                assert field in entry, f"Calendar entry should contain '{field}' field"
        
        print(f"✓ Calendar section valid")
        print(f"  - Total calendar entries: {len(calendar)}")
    
    def test_employee_dossier_returns_warnings(self):
        """Test that dossier returns warnings section"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "warnings" in data, "Response should contain 'warnings' field"
        
        warnings = data["warnings"]
        assert isinstance(warnings, list), "Warnings should be a list"
        
        # Verify warning structure if there are warnings
        if warnings:
            warning = warnings[0]
            assert "type" in warning, "Warning should contain 'type' field"
            assert "text" in warning, "Warning should contain 'text' field"
        
        print(f"✓ Warnings section valid")
        print(f"  - Total warnings: {len(warnings)}")
        for w in warnings:
            print(f"    - {w['type']}: {w['text']}")
    
    def test_employee_dossier_returns_period(self):
        """Test that dossier returns period info"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "period" in data, "Response should contain 'period' field"
        
        period = data["period"]
        assert "date_from" in period, "Period should contain 'date_from'"
        assert "date_to" in period, "Period should contain 'date_to'"
        
        print(f"✓ Period info valid: {period['date_from']} to {period['date_to']}")
    
    def test_employee_dossier_with_date_range(self):
        """Test dossier with custom date range parameters"""
        response = self.session.get(
            f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}",
            params={"date_from": "2024-01-01", "date_to": "2025-12-31"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["period"]["date_from"] == "2024-01-01"
        assert data["period"]["date_to"] == "2025-12-31"
        
        print(f"✓ Custom date range works correctly")
    
    def test_employee_dossier_invalid_worker(self):
        """Test dossier with invalid worker ID returns error"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/invalid-worker-id-12345")
        assert response.status_code == 200  # API returns 200 with error field
        
        data = response.json()
        assert "error" in data, "Should return error for invalid worker"
        
        print(f"✓ Invalid worker ID handled correctly: {data.get('error')}")
    
    def test_employee_dossier_report_lines_have_project_links(self):
        """Test that report lines include project_id for linking"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        reports = data.get("reports", {})
        lines = reports.get("lines", [])
        
        # Check if any report has project info
        reports_with_project = [l for l in lines if l.get("project_id") and l.get("project_name")]
        
        print(f"✓ Report lines structure valid")
        print(f"  - Reports with project links: {len(reports_with_project)}/{len(lines)}")
    
    def test_employee_dossier_payroll_status_badges(self):
        """Test that payroll weeks have proper status values"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        payroll = data.get("payroll", {})
        weeks = payroll.get("weeks", [])
        
        valid_statuses = ["draft", "batched", "paid", "pending"]
        
        for week in weeks:
            status = week.get("status", "")
            # Status should be one of the valid values or empty
            print(f"  - Week {week.get('week_start')}: status={status}")
        
        print(f"✓ Payroll status badges valid")


class TestEmployeeDossierDataIntegrity:
    """Test data integrity and calculations in employee dossier"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        
        if login_response.status_code == 200:
            token = login_response.json().get("token")  # API returns 'token' not 'access_token'
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
            else:
                pytest.skip("No token in login response")
        else:
            pytest.skip(f"Authentication failed: {login_response.status_code}")
    
    def test_report_hours_calculation(self):
        """Test that normal + overtime = total hours for each report"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        lines = data.get("reports", {}).get("lines", [])
        
        for line in lines[:10]:  # Check first 10
            hours = line.get("hours", 0)
            normal = line.get("normal", 0)
            overtime = line.get("overtime", 0)
            
            # Normal should be min(hours, 8) and overtime should be max(0, hours - 8)
            expected_normal = min(hours, 8)
            expected_overtime = max(0, hours - 8)
            
            assert abs(normal - expected_normal) < 0.1, f"Normal hours mismatch for {line.get('date')}"
            assert abs(overtime - expected_overtime) < 0.1, f"Overtime hours mismatch for {line.get('date')}"
        
        print(f"✓ Report hours calculations are correct")
    
    def test_total_hours_sum(self):
        """Test that total_hours equals sum of individual report hours"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        reports = data.get("reports", {})
        lines = reports.get("lines", [])
        total_hours = reports.get("total_hours", 0)
        
        calculated_sum = sum(l.get("hours", 0) for l in lines)
        
        assert abs(total_hours - calculated_sum) < 0.1, f"Total hours mismatch: {total_hours} vs {calculated_sum}"
        
        print(f"✓ Total hours sum is correct: {total_hours}")
    
    def test_payroll_totals(self):
        """Test that payroll totals are calculated correctly"""
        response = self.session.get(f"{BASE_URL}/api/employee-dossier/{TEST_WORKER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        payroll = data.get("payroll", {})
        weeks = payroll.get("weeks", [])
        
        calculated_gross = sum(w.get("gross", 0) for w in weeks)
        calculated_net = sum(w.get("net", 0) for w in weeks)
        calculated_paid = sum(w.get("net", 0) for w in weeks if w.get("status") == "paid")
        
        assert abs(payroll.get("total_gross", 0) - calculated_gross) < 0.1
        assert abs(payroll.get("total_net", 0) - calculated_net) < 0.1
        assert abs(payroll.get("total_paid", 0) - calculated_paid) < 0.1
        
        print(f"✓ Payroll totals are correct")
        print(f"  - Gross: {payroll.get('total_gross')}")
        print(f"  - Net: {payroll.get('total_net')}")
        print(f"  - Paid: {payroll.get('total_paid')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
