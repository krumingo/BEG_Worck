import requests
import sys
import json
from datetime import datetime

class BEGWorkAPITester:
    def __init__(self, base_url="https://beg-work.preview.emergentagent.com"):
        self.base_url = f"{base_url}/api"
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.admin_credentials = {"email": "admin@begwork.com", "password": "admin123"}

    def log_result(self, test_name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")
        if details:
            print(f"    {details}")
        
        if success:
            self.tests_passed += 1
        else:
            self.failed_tests.append({"test": test_name, "details": details})
        return success

    def make_request(self, method, endpoint, data=None, expected_status=200):
        """Make API request with common handling"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=10)
            
            success = response.status_code == expected_status
            return success, response
            
        except Exception as e:
            return False, str(e)

    def test_auth_login(self):
        """Test POST /api/auth/login with admin credentials"""
        success, response = self.make_request('POST', 'auth/login', self.admin_credentials, 200)
        
        if success:
            data = response.json()
            if 'token' in data and 'user' in data:
                self.token = data['token']
                user = data['user']
                if 'password_hash' not in user:  # Should not include password hash
                    return self.log_result("Login with admin credentials", True, 
                                         f"Token received, user data clean")
                else:
                    return self.log_result("Login with admin credentials", False, 
                                         "User data includes password_hash")
            else:
                return self.log_result("Login with admin credentials", False, 
                                     "Missing token or user in response")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("Login with admin credentials", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_auth_me_with_token(self):
        """Test GET /api/auth/me with valid token"""
        if not self.token:
            return self.log_result("GET /auth/me with token", False, "No token available")
        
        success, response = self.make_request('GET', 'auth/me', expected_status=200)
        
        if success:
            data = response.json()
            if 'password_hash' not in data:
                return self.log_result("GET /auth/me with token", True, "User data without password hash")
            else:
                return self.log_result("GET /auth/me with token", False, "Response includes password_hash")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /auth/me with token", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_auth_me_without_token(self):
        """Test GET /api/auth/me without token (should return 401)"""
        temp_token = self.token
        self.token = None
        
        success, response = self.make_request('GET', 'auth/me', expected_status=401)
        self.token = temp_token  # Restore token
        
        return self.log_result("GET /auth/me without token", success, "Should return 401")

    def test_get_organization(self):
        """Test GET /api/organization with valid token"""
        success, response = self.make_request('GET', 'organization', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['id', 'name', 'subscription_plan']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                return self.log_result("GET /organization", True, f"Org: {data.get('name', 'N/A')}")
            else:
                return self.log_result("GET /organization", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /organization", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_put_organization(self):
        """Test PUT /api/organization (Admin only)"""
        update_data = {"name": "Updated BEG_Work Demo", "phone": "+1-555-0123"}
        success, response = self.make_request('PUT', 'organization', update_data, 200)
        
        if success:
            data = response.json()
            if data.get('name') == update_data['name']:
                return self.log_result("PUT /organization", True, "Organization updated successfully")
            else:
                return self.log_result("PUT /organization", False, "Update not reflected in response")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("PUT /organization", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_users(self):
        """Test GET /api/users"""
        success, response = self.make_request('GET', 'users', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                # Check that password_hash is not included
                has_password_hash = any('password_hash' in user for user in data)
                if not has_password_hash:
                    return self.log_result("GET /users", True, f"Found {len(data)} users, no password hashes")
                else:
                    return self.log_result("GET /users", False, "User data includes password_hash")
            else:
                return self.log_result("GET /users", False, "No users found or invalid format")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /users", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_create_user(self):
        """Test POST /api/users (Admin only)"""
        test_user = {
            "email": f"test_{datetime.now().strftime('%H%M%S')}@example.com",
            "password": "TestPass123!",
            "first_name": "Test",
            "last_name": "User", 
            "role": "Viewer",
            "phone": "+1-555-0123"
        }
        
        success, response = self.make_request('POST', 'users', test_user, 201)
        
        if success:
            data = response.json()
            if data.get('email') == test_user['email'] and 'password_hash' not in data:
                self.test_user_id = data.get('id')  # Store for later tests
                return self.log_result("POST /users", True, f"User created: {test_user['email']}")
            else:
                return self.log_result("POST /users", False, "Invalid response or contains password_hash")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /users", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_create_duplicate_user(self):
        """Test POST /api/users with duplicate email (should fail)"""
        duplicate_user = {
            "email": "admin@begwork.com",  # This already exists
            "password": "TestPass123!",
            "first_name": "Duplicate",
            "last_name": "User",
            "role": "Viewer"
        }
        
        success, response = self.make_request('POST', 'users', duplicate_user, 400)
        return self.log_result("POST /users duplicate email", success, "Should reject duplicate email")

    def test_create_user_invalid_role(self):
        """Test POST /api/users with invalid role (should fail)"""
        invalid_user = {
            "email": f"invalid_{datetime.now().strftime('%H%M%S')}@example.com",
            "password": "TestPass123!",
            "first_name": "Invalid",
            "last_name": "Role",
            "role": "InvalidRole"
        }
        
        success, response = self.make_request('POST', 'users', invalid_user, 400)
        return self.log_result("POST /users invalid role", success, "Should reject invalid role")

    def test_update_user(self):
        """Test PUT /api/users/{user_id} (Admin only)"""
        if not hasattr(self, 'test_user_id'):
            return self.log_result("PUT /users/{id}", False, "No test user ID available")
        
        update_data = {
            "first_name": "Updated",
            "last_name": "Name",
            "role": "Technician"
        }
        
        success, response = self.make_request('PUT', f'users/{self.test_user_id}', update_data, 200)
        
        if success:
            data = response.json()
            if data.get('first_name') == 'Updated' and data.get('role') == 'Technician':
                return self.log_result("PUT /users/{id}", True, "User updated successfully")
            else:
                return self.log_result("PUT /users/{id}", False, "Update not reflected")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("PUT /users/{id}", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_delete_user(self):
        """Test DELETE /api/users/{user_id} (Admin only)"""
        if not hasattr(self, 'test_user_id'):
            return self.log_result("DELETE /users/{id}", False, "No test user ID available")
        
        success, response = self.make_request('DELETE', f'users/{self.test_user_id}', expected_status=200)
        
        if success:
            data = response.json()
            if data.get('ok') is True:
                return self.log_result("DELETE /users/{id}", True, "User deleted successfully")
            else:
                return self.log_result("DELETE /users/{id}", False, "Unexpected response format")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("DELETE /users/{id}", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_feature_flags(self):
        """Test GET /api/feature-flags"""
        success, response = self.make_request('GET', 'feature-flags', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list) and len(data) == 10:  # Should have 10 modules
                m0_enabled = any(f['module_code'] == 'M0' and f['enabled'] for f in data)
                if m0_enabled:
                    return self.log_result("GET /feature-flags", True, f"Found {len(data)} modules, M0 enabled")
                else:
                    return self.log_result("GET /feature-flags", False, "M0 module not enabled")
            else:
                return self.log_result("GET /feature-flags", False, f"Expected 10 modules, got {len(data) if isinstance(data, list) else 'non-list'}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /feature-flags", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_toggle_feature_flag(self):
        """Test PUT /api/feature-flags (Admin only)"""
        # Try to enable M1 module
        toggle_data = {"module_code": "M1", "enabled": True}
        success, response = self.make_request('PUT', 'feature-flags', toggle_data, 200)
        
        if success:
            data = response.json()
            m1_flag = next((f for f in data if f['module_code'] == 'M1'), None)
            if m1_flag and m1_flag['enabled']:
                return self.log_result("PUT /feature-flags", True, "M1 module toggled successfully")
            else:
                return self.log_result("PUT /feature-flags", False, "Toggle not reflected in response")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("PUT /feature-flags", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_toggle_core_module(self):
        """Test PUT /api/feature-flags trying to disable M0 (should fail)"""
        toggle_data = {"module_code": "M0", "enabled": False}
        success, response = self.make_request('PUT', 'feature-flags', toggle_data, 400)
        
        return self.log_result("PUT /feature-flags M0 disable", success, "Should reject disabling core module")

    def test_get_audit_logs(self):
        """Test GET /api/audit-logs (Admin only)"""
        success, response = self.make_request('GET', 'audit-logs', expected_status=200)
        
        if success:
            data = response.json()
            if 'logs' in data and 'total' in data:
                logs = data['logs']
                total = data['total']
                if len(logs) > 0 and total >= len(logs):
                    return self.log_result("GET /audit-logs", True, f"Found {len(logs)}/{total} audit entries")
                else:
                    return self.log_result("GET /audit-logs", True, f"No logs yet, total: {total}")
            else:
                return self.log_result("GET /audit-logs", False, "Missing logs or total in response")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /audit-logs", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_roles(self):
        """Test GET /api/roles"""
        success, response = self.make_request('GET', 'roles', expected_status=200)
        
        if success:
            data = response.json()
            expected_roles = ["Admin", "Owner", "SiteManager", "Technician", "Accountant", "Warehousekeeper", "Driver", "Viewer"]
            if isinstance(data, list) and len(data) == 8:
                missing_roles = [r for r in expected_roles if r not in data]
                if not missing_roles:
                    return self.log_result("GET /roles", True, f"Found all 8 roles")
                else:
                    return self.log_result("GET /roles", False, f"Missing roles: {missing_roles}")
            else:
                return self.log_result("GET /roles", False, f"Expected 8 roles, got {len(data) if isinstance(data, list) else 'non-list'}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /roles", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_subscription(self):
        """Test GET /api/subscription"""
        success, response = self.make_request('GET', 'subscription', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['id', 'org_id', 'plan', 'status']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                return self.log_result("GET /subscription", True, f"Plan: {data.get('plan')}, Status: {data.get('status')}")
            else:
                return self.log_result("GET /subscription", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /subscription", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def run_all_tests(self):
        """Run all backend API tests"""
        print("🔬 Starting BEG_Work API Tests")
        print("=" * 50)
        
        # Authentication tests
        self.test_auth_login()
        self.test_auth_me_with_token()
        self.test_auth_me_without_token()
        
        # Organization tests
        self.test_get_organization()
        self.test_put_organization()
        
        # User management tests
        self.test_get_users()
        self.test_create_user()
        self.test_create_duplicate_user()
        self.test_create_user_invalid_role()
        self.test_update_user()
        self.test_delete_user()
        
        # Feature flags tests
        self.test_get_feature_flags()
        self.test_toggle_feature_flag()
        self.test_toggle_core_module()
        
        # Audit logs tests
        self.test_get_audit_logs()
        
        # Misc tests
        self.test_get_roles()
        self.test_get_subscription()
        
        # Final summary
        print("=" * 50)
        print(f"📊 Tests Summary: {self.tests_passed}/{self.tests_run} PASSED")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for test in self.failed_tests:
                print(f"  - {test['test']}: {test['details']}")
        
        success_rate = (self.tests_passed / self.tests_run) * 100 if self.tests_run > 0 else 0
        print(f"📈 Success Rate: {success_rate:.1f}%")
        
        return success_rate >= 80  # Consider test suite passed if 80%+ tests pass

def main():
    tester = BEGWorkAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())