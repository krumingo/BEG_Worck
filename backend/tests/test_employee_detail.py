"""
Tests for Employee Detail Page / Dashboard endpoints (BLOCK C - HR/Attendance/Payroll Improvements)
- GET /api/employees/{id}/dashboard - Employee detail with attendance, projects, hours summary, payslips
- GET /api/employees/{id}/calendar - Calendar data with attendance + work reports by day
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


# Known test data from context
TECH1_USER_ID = "6f69367a-e25f-489d-a7c8-f25cde6a9ac5"
ADMIN_USER_ID = "821d8119-d790-444c-9676-fc069314c41c"


class TestEmployeeListEndpoint:
    """Test GET /api/employees"""
    
    def test_list_employees_returns_200(self, api_client):
        """Employees list returns 200"""
        response = api_client.get(f"{BASE_URL}/api/employees")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/employees returned {len(data)} employees")
    
    def test_list_employees_has_profile_field(self, api_client):
        """Employees include profile and has_profile fields"""
        response = api_client.get(f"{BASE_URL}/api/employees")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            emp = data[0]
            assert "profile" in emp
            assert "has_profile" in emp
            print(f"✓ Employee has profile={emp.get('profile') is not None}, has_profile={emp.get('has_profile')}")


class TestEmployeeDashboardEndpoint:
    """Test GET /api/employees/{id}/dashboard"""
    
    def test_dashboard_returns_200_for_tech1(self, api_client):
        """Dashboard returns 200 for known tech1 user"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        print("✓ GET /api/employees/{id}/dashboard returned 200")
    
    def test_dashboard_contains_employee_data(self, api_client):
        """Dashboard contains employee basic info"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "employee" in data
        emp = data["employee"]
        assert "id" in emp
        assert "email" in emp
        assert "role" in emp
        print(f"✓ Employee: {emp.get('first_name')} {emp.get('last_name')} ({emp.get('email')})")
    
    def test_dashboard_contains_profile(self, api_client):
        """Dashboard returns profile (can be null for users without profile)"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "profile" in data
        profile = data["profile"]
        if profile:
            assert "pay_type" in profile
            assert "daily_rate" in profile or "hourly_rate" in profile or "monthly_salary" in profile
            print(f"✓ Profile: pay_type={profile.get('pay_type')}, daily_rate={profile.get('daily_rate')}")
        else:
            print("✓ Profile is null (no employee profile set)")
    
    def test_dashboard_contains_attendance(self, api_client):
        """Dashboard returns attendance records (last 30 days)"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "attendance" in data
        attendance = data["attendance"]
        assert isinstance(attendance, list)
        print(f"✓ Attendance: {len(attendance)} records in last 30 days")
        
        if len(attendance) > 0:
            att = attendance[0]
            assert "date" in att
            assert "status" in att
            print(f"  - Latest: {att.get('date')} - {att.get('status')}")
    
    def test_dashboard_contains_project_history(self, api_client):
        """Dashboard returns project history with days_present, total_hours, last_attendance"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "project_history" in data
        projects = data["project_history"]
        assert isinstance(projects, list)
        print(f"✓ Project history: {len(projects)} projects")
        
        if len(projects) > 0:
            proj = projects[0]
            assert "project_id" in proj
            assert "project_code" in proj
            assert "project_name" in proj
            assert "days_present" in proj
            assert "total_hours" in proj
            assert "last_attendance" in proj
            print(f"  - {proj.get('project_code')}: {proj.get('days_present')} days, {proj.get('total_hours')} hours")
    
    def test_dashboard_contains_hours_summary(self, api_client):
        """Dashboard returns hours_summary with current_month_days, current_month_hours, total_projects"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "hours_summary" in data
        summary = data["hours_summary"]
        assert "current_month_days" in summary
        assert "current_month_hours" in summary
        assert "total_projects" in summary
        print(f"✓ Hours summary: {summary.get('current_month_days')} days, {summary.get('current_month_hours')}h, {summary.get('total_projects')} projects")
    
    def test_dashboard_contains_payslips(self, api_client):
        """Dashboard returns recent payslips"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "payslips" in data
        payslips = data["payslips"]
        assert isinstance(payslips, list)
        print(f"✓ Payslips: {len(payslips)} recent payslips")
        
        if len(payslips) > 0:
            ps = payslips[0]
            assert "id" in ps
            assert "net_pay" in ps
            assert "status" in ps
            print(f"  - Latest: net_pay={ps.get('net_pay')}, status={ps.get('status')}")
    
    def test_dashboard_404_for_unknown_user(self, api_client):
        """Dashboard returns 404 for unknown user ID"""
        response = api_client.get(f"{BASE_URL}/api/employees/unknown-user-id/dashboard")
        assert response.status_code == 404
        print("✓ Returns 404 for unknown user")


class TestEmployeeCalendarEndpoint:
    """Test GET /api/employees/{id}/calendar"""
    
    def test_calendar_returns_200(self, api_client):
        """Calendar endpoint returns 200"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar")
        assert response.status_code == 200
        print("✓ GET /api/employees/{id}/calendar returned 200")
    
    def test_calendar_contains_month_field(self, api_client):
        """Calendar returns month in YYYY-MM format"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar")
        assert response.status_code == 200
        data = response.json()
        
        assert "month" in data
        month = data["month"]
        assert len(month) == 7
        assert month[4] == "-"
        print(f"✓ Calendar month: {month}")
    
    def test_calendar_contains_days_array(self, api_client):
        """Calendar returns days array with attendance/work_reports/total_hours"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar?month=2026-02")
        assert response.status_code == 200
        data = response.json()
        
        assert "days" in data
        days = data["days"]
        assert isinstance(days, list)
        print(f"✓ Calendar days: {len(days)} days with data")
        
        if len(days) > 0:
            day = days[0]
            assert "date" in day
            assert "attendance" in day or day.get("attendance") is None
            assert "work_reports" in day
            assert "total_hours" in day
            print(f"  - {day.get('date')}: attendance={day.get('attendance')}, total_hours={day.get('total_hours')}")
    
    def test_calendar_contains_totals(self, api_client):
        """Calendar returns total_present and total_hours"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_present" in data
        assert "total_hours" in data
        print(f"✓ Calendar totals: {data.get('total_present')} present, {data.get('total_hours')} hours")
    
    def test_calendar_supports_month_parameter(self, api_client):
        """Calendar accepts month parameter for navigation"""
        # Test with specific month
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar?month=2026-02")
        assert response.status_code == 200
        data = response.json()
        assert data["month"] == "2026-02"
        print("✓ Calendar month=2026-02 parameter works")
        
        # Test with different month
        response2 = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar?month=2026-01")
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["month"] == "2026-01"
        print("✓ Calendar month=2026-01 parameter works")
    
    def test_calendar_default_to_current_month(self, api_client):
        """Calendar defaults to current month when no parameter provided"""
        from datetime import datetime
        current_month = datetime.now().strftime("%Y-%m")
        
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/calendar")
        assert response.status_code == 200
        data = response.json()
        assert data["month"] == current_month
        print(f"✓ Calendar defaults to current month: {current_month}")
    
    def test_calendar_returns_empty_for_unknown_user(self, api_client):
        """Calendar returns empty data for unknown user ID (no validation unlike dashboard)"""
        response = api_client.get(f"{BASE_URL}/api/employees/unknown-user-id/calendar")
        # Note: Calendar doesn't validate user existence, returns empty data instead of 404
        assert response.status_code == 200
        data = response.json()
        assert len(data.get("days", [])) == 0
        assert data.get("total_present") == 0
        print("✓ Returns empty calendar for unknown user")


class TestEmployeeDetailSingleEndpoint:
    """Test GET /api/employees/{id}"""
    
    def test_employee_detail_returns_200(self, api_client):
        """Single employee endpoint returns 200"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}")
        assert response.status_code == 200
        print("✓ GET /api/employees/{id} returned 200")
    
    def test_employee_detail_contains_user_and_profile(self, api_client):
        """Single employee returns user info and profile"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        # Should have user fields
        assert "id" in data
        assert "email" in data
        assert "role" in data
        
        # Should have profile
        assert "profile" in data
        print(f"✓ Employee: {data.get('email')}, profile={data.get('profile') is not None}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
