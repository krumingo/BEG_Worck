"""
Test suite for New Employee HR Flow.
Tests:
1. POST /api/users creates new user with phone field
2. POST /api/employees creates employee profile with working_days_per_month
3. GET /api/employees returns avatar_url, phone, first_name, last_name
4. PUT /api/employees/{id}/basic accepts avatar_url field
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Valid passwords from test utils
VALID_ADMIN_PASSWORD = "AdminTest123!Secure"
VALID_NEW_USER_PASSWORD = "NewUser123!Test"


class TestNewEmployeeHRFlow:
    """Tests for the New Employee creation flow in HR module"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        self.session = requests.Session()
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json()["token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self.user_data = response.json().get("user", {})
    
    # ══════════════════════════════════════════════════════════════════════════
    # Test 1: POST /api/users creates new user with phone field
    # ══════════════════════════════════════════════════════════════════════════
    
    def test_create_user_with_phone(self):
        """POST /api/users creates new user with phone field"""
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_new_{unique_id}@begwork.com"
        test_phone = f"+35988812{unique_id[:4]}"
        
        response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "Test",
                "last_name": "NewUser",
                "role": "Technician",
                "phone": test_phone
            }
        )
        
        assert response.status_code == 201, f"Create user failed: {response.text}"
        data = response.json()
        
        # Verify user data
        assert data.get("id"), "User ID should be returned"
        assert data.get("email") == test_email, "Email should match"
        assert data.get("first_name") == "Test", "First name should match"
        assert data.get("last_name") == "NewUser", "Last name should match"
        assert data.get("phone") == test_phone, "Phone should match"
        assert data.get("role") == "Technician", "Role should match"
        
        # Store user ID for cleanup
        self.__class__.test_user_id = data.get("id")
        print(f"PASS: Created user with phone: {test_phone}")
    
    def test_create_user_without_phone(self):
        """POST /api/users creates user without phone (optional field)"""
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_nophone_{unique_id}@begwork.com"
        
        response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "NoPhone",
                "last_name": "User",
                "role": "Viewer"
            }
        )
        
        assert response.status_code == 201, f"Create user without phone failed: {response.text}"
        data = response.json()
        assert data.get("phone") == "" or data.get("phone") is None, "Phone should be empty or None"
        
        # Cleanup
        self.__class__.test_user_id_nophone = data.get("id")
        print("PASS: Created user without phone")
    
    # ══════════════════════════════════════════════════════════════════════════
    # Test 2: POST /api/employees creates employee profile with working_days_per_month
    # ══════════════════════════════════════════════════════════════════════════
    
    def test_create_employee_profile_with_working_days(self):
        """POST /api/employees creates profile with working_days_per_month"""
        # First create a user to assign profile to
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_profile_{unique_id}@begwork.com"
        
        user_response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "Profile",
                "last_name": "Test",
                "role": "Technician",
                "phone": "+359888111222"
            }
        )
        assert user_response.status_code == 201, f"Create user failed: {user_response.text}"
        user_id = user_response.json()["id"]
        self.__class__.test_profile_user_id = user_id
        
        # Create employee profile
        response = self.session.post(
            f"{BASE_URL}/api/employees",
            json={
                "user_id": user_id,
                "pay_type": "Monthly",
                "monthly_salary": 2500.00,
                "daily_rate": 113.64,
                "hourly_rate": 14.20,
                "working_days_per_month": 22,
                "standard_hours_per_day": 8,
                "active": True
            }
        )
        
        assert response.status_code == 201, f"Create profile failed: {response.text}"
        data = response.json()
        
        # Verify profile data
        assert data.get("user_id") == user_id, "User ID should match"
        assert data.get("pay_type") == "Monthly", "Pay type should match"
        assert data.get("monthly_salary") == 2500.00, "Monthly salary should match"
        assert data.get("working_days_per_month") == 22, "Working days per month should match"
        assert data.get("standard_hours_per_day") == 8, "Standard hours per day should match"
        assert data.get("active") == True, "Active status should match"
        
        print(f"PASS: Created employee profile with working_days_per_month=22")
    
    def test_create_employee_profile_daily_rate(self):
        """POST /api/employees creates profile with Daily pay type"""
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_daily_{unique_id}@begwork.com"
        
        user_response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "Daily",
                "last_name": "Worker",
                "role": "Technician"
            }
        )
        assert user_response.status_code == 201
        user_id = user_response.json()["id"]
        self.__class__.test_daily_user_id = user_id
        
        response = self.session.post(
            f"{BASE_URL}/api/employees",
            json={
                "user_id": user_id,
                "pay_type": "Daily",
                "daily_rate": 100.00,
                "hourly_rate": 12.50,
                "working_days_per_month": 20,
                "standard_hours_per_day": 8,
                "active": True
            }
        )
        
        assert response.status_code == 201, f"Create daily profile failed: {response.text}"
        data = response.json()
        assert data.get("pay_type") == "Daily", "Pay type should be Daily"
        assert data.get("daily_rate") == 100.00, "Daily rate should match"
        
        print("PASS: Created employee profile with Daily pay type")
    
    # ══════════════════════════════════════════════════════════════════════════
    # Test 3: GET /api/employees returns avatar_url, phone, first_name, last_name
    # ══════════════════════════════════════════════════════════════════════════
    
    def test_get_employees_returns_all_fields(self):
        """GET /api/employees returns avatar_url, phone, first_name, last_name"""
        response = self.session.get(f"{BASE_URL}/api/employees")
        
        assert response.status_code == 200, f"Get employees failed: {response.text}"
        employees = response.json()
        
        assert isinstance(employees, list), "Response should be a list"
        assert len(employees) > 0, "Should have at least one employee"
        
        # Check first employee has all required fields
        emp = employees[0]
        
        # Required fields from the query
        required_fields = ["id", "email", "role"]
        for field in required_fields:
            assert field in emp, f"Employee should have '{field}' field"
        
        # New fields that should be present (may be null/empty but field must exist in response)
        # Note: avatar_url may not exist in response if never set - check employees with profiles
        emp_with_profile = next((e for e in employees if e.get("profile") is not None), emp)
        
        # phone, first_name, last_name should be in all employee objects
        for field in ["first_name", "last_name", "phone"]:
            assert field in emp_with_profile, f"Employee should have '{field}' field"
        
        # Check that at least one employee has avatar_url in response (might be null if not set)
        # This verifies the query includes avatar_url field
        has_avatar_field = any("avatar_url" in e for e in employees)
        assert has_avatar_field, "At least one employee should have avatar_url field in response"
        
        print(f"PASS: GET /api/employees returns all required fields including phone, first_name, last_name")
        print(f"  Sample employee keys: {list(emp_with_profile.keys())}")
    
    def test_get_employees_phone_populated(self):
        """GET /api/employees returns phone for employees with phone set"""
        # First create user with phone
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_phone_check_{unique_id}@begwork.com"
        test_phone = "+359888555777"
        
        user_response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "PhoneTest",
                "last_name": "User",
                "role": "Technician",
                "phone": test_phone
            }
        )
        assert user_response.status_code == 201
        new_user_id = user_response.json()["id"]
        self.__class__.test_phone_check_user_id = new_user_id
        
        # Get employees list
        response = self.session.get(f"{BASE_URL}/api/employees")
        assert response.status_code == 200
        
        employees = response.json()
        
        # Find our test user
        test_emp = next((e for e in employees if e.get("id") == new_user_id), None)
        assert test_emp is not None, "Created user should appear in employees list"
        assert test_emp.get("phone") == test_phone, f"Phone should be {test_phone}, got {test_emp.get('phone')}"
        
        print(f"PASS: Phone field correctly returned: {test_emp.get('phone')}")
    
    # ══════════════════════════════════════════════════════════════════════════
    # Test 4: PUT /api/employees/{id}/basic accepts avatar_url field
    # ══════════════════════════════════════════════════════════════════════════
    
    def test_update_employee_basic_with_avatar_url(self):
        """PUT /api/employees/{id}/basic accepts avatar_url field"""
        # Get existing tech1 user
        response = self.session.get(f"{BASE_URL}/api/employees")
        assert response.status_code == 200
        employees = response.json()
        
        # Find tech1 or any technician
        test_emp = next((e for e in employees if "tech1" in e.get("email", "")), None)
        if not test_emp:
            test_emp = next((e for e in employees if e.get("role") == "Technician"), None)
        
        assert test_emp is not None, "Should have a technician employee to test"
        emp_id = test_emp["id"]
        
        # Update with avatar_url
        test_avatar_url = "/api/media/test-avatar-123/file"
        response = self.session.put(
            f"{BASE_URL}/api/employees/{emp_id}/basic",
            json={
                "avatar_url": test_avatar_url
            }
        )
        
        assert response.status_code == 200, f"Update basic failed: {response.text}"
        data = response.json()
        assert data.get("avatar_url") == test_avatar_url, "Avatar URL should be updated"
        
        print(f"PASS: PUT /api/employees/{emp_id}/basic accepts avatar_url field")
    
    def test_update_employee_basic_all_fields(self):
        """PUT /api/employees/{id}/basic accepts all allowed fields"""
        # Create a test user
        unique_id = str(uuid.uuid4())[:8]
        test_email = f"test_basic_update_{unique_id}@begwork.com"
        
        user_response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": test_email,
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "Original",
                "last_name": "Name",
                "role": "Technician",
                "phone": "+359000000000"
            }
        )
        assert user_response.status_code == 201
        user_id = user_response.json()["id"]
        self.__class__.test_basic_update_user_id = user_id
        
        # Update all basic fields
        response = self.session.put(
            f"{BASE_URL}/api/employees/{user_id}/basic",
            json={
                "first_name": "Updated",
                "last_name": "NameChanged",
                "phone": "+359888999111",
                "avatar_url": "/api/media/updated-avatar/file"
            }
        )
        
        assert response.status_code == 200, f"Update failed: {response.text}"
        data = response.json()
        
        assert data.get("first_name") == "Updated", "First name should be updated"
        assert data.get("last_name") == "NameChanged", "Last name should be updated"
        assert data.get("phone") == "+359888999111", "Phone should be updated"
        assert data.get("avatar_url") == "/api/media/updated-avatar/file", "Avatar URL should be updated"
        
        print("PASS: PUT /api/employees/{id}/basic updates all allowed fields")
    
    # ══════════════════════════════════════════════════════════════════════════
    # Test Full Create Employee Flow (User + Profile)
    # ══════════════════════════════════════════════════════════════════════════
    
    def test_full_create_employee_flow(self):
        """Test complete flow: Create User -> Create Profile"""
        unique_id = str(uuid.uuid4())[:8]
        
        # Step 1: Create user
        user_response = self.session.post(
            f"{BASE_URL}/api/users",
            json={
                "email": f"fullflow_{unique_id}@begwork.com",
                "password": VALID_NEW_USER_PASSWORD,
                "first_name": "FullFlow",
                "last_name": "Employee",
                "role": "Technician",
                "phone": "+359888777666"
            }
        )
        assert user_response.status_code == 201, "Step 1: Create user failed"
        user_id = user_response.json()["id"]
        self.__class__.test_fullflow_user_id = user_id
        print(f"Step 1: Created user with ID: {user_id}")
        
        # Step 2: Create employee profile
        profile_response = self.session.post(
            f"{BASE_URL}/api/employees",
            json={
                "user_id": user_id,
                "pay_type": "Monthly",
                "monthly_salary": 3000.00,
                "working_days_per_month": 22,
                "standard_hours_per_day": 8,
                "active": True
            }
        )
        assert profile_response.status_code == 201, f"Step 2: Create profile failed: {profile_response.text}"
        profile = profile_response.json()
        print(f"Step 2: Created profile with monthly_salary: {profile.get('monthly_salary')}")
        
        # Step 3: Verify employee appears in list with all fields
        list_response = self.session.get(f"{BASE_URL}/api/employees")
        assert list_response.status_code == 200
        employees = list_response.json()
        
        new_emp = next((e for e in employees if e.get("id") == user_id), None)
        assert new_emp is not None, "New employee should appear in list"
        assert new_emp.get("first_name") == "FullFlow", "First name should match"
        assert new_emp.get("phone") == "+359888777666", "Phone should match"
        assert new_emp.get("profile") is not None, "Profile should be attached"
        assert new_emp["profile"].get("monthly_salary") == 3000.00, "Monthly salary should match"
        
        print("PASS: Full create employee flow works correctly")


class TestEmployeeListFields:
    """Additional tests for employee list response fields"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        self.session = requests.Session()
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json()["token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
    
    def test_employees_list_structure(self):
        """Verify employees list structure includes all expected fields"""
        response = self.session.get(f"{BASE_URL}/api/employees")
        assert response.status_code == 200
        
        employees = response.json()
        assert len(employees) > 0, "Should have employees"
        
        # Check structure of response
        emp = employees[0]
        
        # Fields from the query in hr.py line 39
        expected_fields = ["id", "first_name", "last_name", "name", "email", "role", "phone", "avatar_url"]
        for field in expected_fields:
            # name might not exist for newer users, that's OK
            if field != "name":
                assert field in emp, f"Missing field: {field}"
        
        # Check profile structure
        assert "profile" in emp or "has_profile" in emp, "Should have profile info"
        
        print(f"PASS: Employee list structure is correct")
        print(f"  Fields present: {list(emp.keys())}")


class TestCleanup:
    """Cleanup test users created during tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        self.session = requests.Session()
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        if response.status_code == 200:
            self.token = response.json()["token"]
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
    
    def test_cleanup_test_users(self):
        """Clean up test users (run last)"""
        # Get all users
        response = self.session.get(f"{BASE_URL}/api/users")
        if response.status_code != 200:
            print("Could not fetch users for cleanup")
            return
        
        users = response.json()
        deleted = 0
        
        # Delete test users (those with test_ prefix in email)
        for user in users:
            email = user.get("email", "")
            if email.startswith("test_") or email.startswith("fullflow_"):
                del_response = self.session.delete(f"{BASE_URL}/api/auth/users/{user['id']}")
                if del_response.status_code in [200, 404]:
                    deleted += 1
        
        print(f"Cleanup: Deleted {deleted} test users")
