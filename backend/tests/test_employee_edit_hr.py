"""
Tests for Employee Edit Feature - HR Fix (iteration 38)
- PUT /api/employees/{id}/basic - Update phone, name
- PUT /api/employees/{id} - Update pay_type, monthly_salary, daily_rate, hourly_rate, working_days_per_month
- Auto-calculation: daily = monthly/22, hourly = daily/8
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known test data from context - tech1 employee
TECH1_USER_ID = "6f69367a-e25f-489d-a7c8-f25cde6a9ac5"


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


class TestEmployeeBasicUpdate:
    """Test PUT /api/employees/{id}/basic - Update basic info (name, phone)"""
    
    def test_update_basic_phone(self, api_client):
        """Update employee phone number"""
        test_phone = "+359888111222"
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}/basic",
            json={"phone": test_phone}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("phone") == test_phone
        print(f"✓ PUT /employees/{TECH1_USER_ID}/basic phone update returned 200")
        print(f"  Phone: {data.get('phone')}")
    
    def test_update_basic_first_name(self, api_client):
        """Update employee first_name"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}/basic",
            json={"first_name": "Тест"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("first_name") == "Тест"
        print(f"✓ first_name updated to: {data.get('first_name')}")
    
    def test_update_basic_last_name(self, api_client):
        """Update employee last_name"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}/basic",
            json={"last_name": "Техник"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("last_name") == "Техник"
        print(f"✓ last_name updated to: {data.get('last_name')}")
    
    def test_update_basic_multiple_fields(self, api_client):
        """Update multiple fields at once"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}/basic",
            json={
                "first_name": "tech1",
                "last_name": "Работник",
                "phone": "+359888123456"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("first_name") == "tech1"
        assert data.get("last_name") == "Работник"
        assert data.get("phone") == "+359888123456"
        print(f"✓ Multiple fields updated: {data.get('first_name')} {data.get('last_name')}, phone={data.get('phone')}")
    
    def test_update_basic_404_for_unknown_user(self, api_client):
        """Returns 404 for unknown user"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/unknown-user-id/basic",
            json={"phone": "+359888111222"}
        )
        assert response.status_code == 404
        print("✓ Returns 404 for unknown user")


class TestEmployeeProfileUpdate:
    """Test PUT /api/employees/{id} - Update pay profile"""
    
    def test_update_profile_pay_type(self, api_client):
        """Update pay_type"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"pay_type": "Monthly"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("pay_type") == "Monthly"
        print(f"✓ PUT /employees/{TECH1_USER_ID} pay_type update returned 200")
        print(f"  pay_type: {data.get('pay_type')}")
    
    def test_update_profile_monthly_salary(self, api_client):
        """Update monthly_salary"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"monthly_salary": 2500.00}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("monthly_salary") == 2500.00
        print(f"✓ monthly_salary updated to: {data.get('monthly_salary')} EUR")
    
    def test_update_profile_daily_rate(self, api_client):
        """Update daily_rate"""
        # Expected auto-calculation for monthly 2500: 2500/22 = ~113.64
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"daily_rate": 113.64}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("daily_rate") == 113.64
        print(f"✓ daily_rate updated to: {data.get('daily_rate')} EUR")
    
    def test_update_profile_hourly_rate(self, api_client):
        """Update hourly_rate"""
        # Expected auto-calculation for daily 113.64: 113.64/8 = ~14.21
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"hourly_rate": 14.21}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("hourly_rate") == 14.21
        print(f"✓ hourly_rate updated to: {data.get('hourly_rate')} EUR/ч")
    
    def test_update_profile_working_days(self, api_client):
        """Update working_days_per_month"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"working_days_per_month": 22}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("working_days_per_month") == 22
        print(f"✓ working_days_per_month updated to: {data.get('working_days_per_month')}")
    
    def test_update_profile_standard_hours(self, api_client):
        """Update standard_hours_per_day"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"standard_hours_per_day": 8}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("standard_hours_per_day") == 8
        print(f"✓ standard_hours_per_day updated to: {data.get('standard_hours_per_day')}")
    
    def test_update_profile_active_status(self, api_client):
        """Update active status"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={"active": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("active") == True
        print(f"✓ active updated to: {data.get('active')}")
    
    def test_update_profile_full_pay_settings(self, api_client):
        """Update all pay settings at once (like frontend save)"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/{TECH1_USER_ID}",
            json={
                "pay_type": "Monthly",
                "monthly_salary": 2200.00,
                "daily_rate": 100.00,  # 2200/22 = 100
                "hourly_rate": 12.50,  # 100/8 = 12.5
                "working_days_per_month": 22,
                "standard_hours_per_day": 8,
                "active": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("pay_type") == "Monthly"
        assert data.get("monthly_salary") == 2200.00
        assert data.get("daily_rate") == 100.00
        assert data.get("hourly_rate") == 12.50
        assert data.get("working_days_per_month") == 22
        assert data.get("standard_hours_per_day") == 8
        assert data.get("active") == True
        print(f"✓ Full profile update: Monthly={data.get('monthly_salary')} EUR, daily={data.get('daily_rate')} EUR, hourly={data.get('hourly_rate')} EUR/ч")
    
    def test_update_profile_404_without_profile(self, api_client):
        """Returns 404 for user without existing profile"""
        response = api_client.put(
            f"{BASE_URL}/api/employees/unknown-user-id",
            json={"pay_type": "Monthly"}
        )
        assert response.status_code == 404
        print("✓ Returns 404 for unknown user profile")


class TestEmployeeDashboardAfterUpdate:
    """Test GET /api/employees/{id}/dashboard returns updated data"""
    
    def test_dashboard_shows_updated_phone(self, api_client):
        """Dashboard shows updated phone from basic info"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        employee = data.get("employee", {})
        assert employee.get("phone") == "+359888123456"
        print(f"✓ Dashboard shows phone: {employee.get('phone')}")
    
    def test_dashboard_shows_updated_profile(self, api_client):
        """Dashboard shows updated profile with pay info"""
        response = api_client.get(f"{BASE_URL}/api/employees/{TECH1_USER_ID}/dashboard")
        assert response.status_code == 200
        data = response.json()
        profile = data.get("profile", {})
        
        assert profile.get("pay_type") == "Monthly"
        assert profile.get("monthly_salary") == 2200.00
        assert profile.get("daily_rate") == 100.00
        assert profile.get("hourly_rate") == 12.50
        assert profile.get("working_days_per_month") == 22
        assert profile.get("standard_hours_per_day") == 8
        print(f"✓ Dashboard profile: type={profile.get('pay_type')}, monthly={profile.get('monthly_salary')} EUR")
        print(f"  daily={profile.get('daily_rate')} EUR, hourly={profile.get('hourly_rate')} EUR/ч")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
