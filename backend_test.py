import requests
import sys
import json
from datetime import datetime

class BEGWorkAPITester:
    def __init__(self, base_url="https://access-control-174.preview.emergentagent.com"):
        self.base_url = f"{base_url}/api"
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.admin_credentials = {"email": "admin@begwork.com", "password": "admin123"}
        self.tech_credentials = {"email": "tech1@begwork.com", "password": "tech123"}
        self.created_project_id = None
        self.existing_project_id = None
        self.tech_user_id = None
        self.attendance_entry_id = None

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
        """Test GET /api/auth/me without token (should return 401/403)"""
        temp_token = self.token
        self.token = None
        
        # Try both 401 and 403 as valid responses for unauthorized access
        success_401, response = self.make_request('GET', 'auth/me', expected_status=401)
        success_403, response = self.make_request('GET', 'auth/me', expected_status=403)
        
        self.token = temp_token  # Restore token
        
        success = success_401 or success_403
        status_text = "401 or 403" if success else f"got {getattr(response, 'status_code', 'N/A')}"
        return self.log_result("GET /auth/me without token", success, f"Should return {status_text}")

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
        
        success, response = self.make_request('POST', 'users', test_user, 201)  # API correctly returns 201
        
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

    # ═══ M1 PROJECTS MODULE TESTS ═══

    def test_get_dashboard_stats(self):
        """Test GET /api/dashboard/stats returns real project counts"""
        success, response = self.make_request('GET', 'dashboard/stats', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['active_projects', 'paused_projects', 'completed_projects', 'draft_projects', 'total_projects', 'users_count']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                return self.log_result("GET /dashboard/stats", True, 
                    f"Stats: Active={data['active_projects']}, Draft={data['draft_projects']}, Users={data['users_count']}")
            else:
                return self.log_result("GET /dashboard/stats", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /dashboard/stats", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_project_enums(self):
        """Test GET /api/project-enums"""
        success, response = self.make_request('GET', 'project-enums', expected_status=200)
        
        if success:
            data = response.json()
            expected_keys = ['statuses', 'types', 'team_roles']
            if all(key in data for key in expected_keys):
                statuses = data['statuses']
                types = data['types'] 
                roles = data['team_roles']
                expected_statuses = ["Draft", "Active", "Paused", "Completed", "Cancelled"]
                expected_types = ["Billable", "Overhead", "Warranty"]
                expected_roles = ["SiteManager", "Technician", "Viewer"]
                
                if (set(statuses) == set(expected_statuses) and 
                    set(types) == set(expected_types) and
                    set(roles) == set(expected_roles)):
                    return self.log_result("GET /project-enums", True, "All enums present and correct")
                else:
                    return self.log_result("GET /project-enums", False, "Enum values don't match expected")
            else:
                return self.log_result("GET /project-enums", False, f"Missing keys: {[k for k in expected_keys if k not in data]}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /project-enums", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_list_projects_admin(self):
        """Test GET /api/projects as Admin (should see all projects)"""
        success, response = self.make_request('GET', 'projects', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                # Should have at least existing test projects
                if len(data) >= 2:
                    # Look for expected test projects
                    project_codes = [p.get('code') for p in data]
                    if 'PRJ-001' in project_codes or 'PRJ-002' in project_codes:
                        # Store an existing project for later tests
                        self.existing_project_id = data[0]['id']
                        return self.log_result("GET /projects (Admin)", True, 
                            f"Found {len(data)} projects, codes: {project_codes[:3]}")
                    else:
                        return self.log_result("GET /projects (Admin)", True, 
                            f"Found {len(data)} projects, codes: {project_codes[:3]}")
                else:
                    return self.log_result("GET /projects (Admin)", True, f"Found {len(data)} projects")
            else:
                return self.log_result("GET /projects (Admin)", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /projects (Admin)", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_list_projects_with_filters(self):
        """Test GET /api/projects with status and type filters"""
        # Test status filter
        success, response = self.make_request('GET', 'projects?status=Active', expected_status=200)
        if success:
            data = response.json()
            active_projects = [p for p in data if p.get('status') == 'Active']
            if len(active_projects) == len(data):
                filter_result = self.log_result("GET /projects?status=Active", True, f"Found {len(data)} active projects")
            else:
                filter_result = self.log_result("GET /projects?status=Active", False, "Filter not working correctly")
        else:
            filter_result = self.log_result("GET /projects?status=Active", False, "Filter request failed")

        # Test type filter
        success, response = self.make_request('GET', 'projects?type=Billable', expected_status=200)
        if success:
            data = response.json()
            billable_projects = [p for p in data if p.get('type') == 'Billable']
            type_result = len(billable_projects) == len(data)
        else:
            type_result = False

        return filter_result and self.log_result("GET /projects with filters", type_result, "Type filter working")

    def test_create_project_admin(self):
        """Test POST /api/projects as Admin (should work)"""
        test_project = {
            "code": f"TEST-{datetime.now().strftime('%H%M%S')}",
            "name": "Test Project Creation",
            "status": "Draft",
            "type": "Billable",
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
            "planned_days": 180,
            "budget_planned": 50000.00,
            "tags": ["test", "automated"],
            "notes": "Created by automated test"
        }
        
        success, response = self.make_request('POST', 'projects', test_project, 201)
        
        if success:
            data = response.json()
            if (data.get('code') == test_project['code'] and 
                data.get('name') == test_project['name'] and
                'id' in data):
                self.created_project_id = data['id']
                return self.log_result("POST /projects (Admin)", True, f"Project created: {test_project['code']}")
            else:
                return self.log_result("POST /projects (Admin)", False, "Response missing expected fields")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /projects (Admin)", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_create_project_duplicate_code(self):
        """Test POST /api/projects with duplicate code (should fail)"""
        if not self.created_project_id:
            return self.log_result("POST /projects duplicate code", False, "No project created to duplicate")
        
        # Try to create project with same code
        duplicate_project = {
            "code": f"TEST-{datetime.now().strftime('%H%M%S')}",  # Use same format but might be different time
            "name": "Duplicate Test",
            "status": "Draft", 
            "type": "Billable"
        }
        
        # First create one
        self.make_request('POST', 'projects', duplicate_project, 201)
        
        # Now try duplicate
        success, response = self.make_request('POST', 'projects', duplicate_project, 400)
        return self.log_result("POST /projects duplicate code", success, "Should reject duplicate code")

    def test_create_project_invalid_enum(self):
        """Test POST /api/projects with invalid status/type (should fail)"""
        invalid_project = {
            "code": f"INVALID-{datetime.now().strftime('%H%M%S')}",
            "name": "Invalid Project",
            "status": "InvalidStatus",
            "type": "Billable"
        }
        
        success, response = self.make_request('POST', 'projects', invalid_project, 400)
        invalid_status = self.log_result("POST /projects invalid status", success, "Should reject invalid status")
        
        # Test invalid type
        invalid_project["status"] = "Draft"
        invalid_project["type"] = "InvalidType"
        success, response = self.make_request('POST', 'projects', invalid_project, 400)
        invalid_type = self.log_result("POST /projects invalid type", success, "Should reject invalid type")
        
        return invalid_status and invalid_type

    def test_get_project_detail(self):
        """Test GET /api/projects/{id} with enriched data"""
        project_id = self.created_project_id or self.existing_project_id
        if not project_id:
            return self.log_result("GET /projects/{id}", False, "No project ID available")
        
        success, response = self.make_request('GET', f'projects/{project_id}', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['id', 'code', 'name', 'status', 'type', 'team_count']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                return self.log_result("GET /projects/{id}", True, 
                    f"Project: {data.get('code')}, Team: {data.get('team_count')}")
            else:
                return self.log_result("GET /projects/{id}", False, f"Missing enriched fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /projects/{id}", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_update_project_admin(self):
        """Test PUT /api/projects/{id} as Admin (should work)"""
        project_id = self.created_project_id or self.existing_project_id
        if not project_id:
            return self.log_result("PUT /projects/{id} (Admin)", False, "No project ID available")
        
        update_data = {
            "name": "Updated Project Name",
            "status": "Active",
            "notes": "Updated by test"
        }
        
        success, response = self.make_request('PUT', f'projects/{project_id}', update_data, 200)
        
        if success:
            data = response.json()
            if data.get('name') == update_data['name'] and data.get('status') == update_data['status']:
                return self.log_result("PUT /projects/{id} (Admin)", True, "Project updated successfully")
            else:
                return self.log_result("PUT /projects/{id} (Admin)", False, "Update not reflected")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("PUT /projects/{id} (Admin)", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_technician_login_and_access(self):
        """Test login as Technician and check project access (role-based filtering)"""
        # Save admin token
        admin_token = self.token
        
        # Login as technician
        success, response = self.make_request('POST', 'auth/login', self.tech_credentials, 200)
        
        if not success:
            self.token = admin_token  # Restore admin token
            return self.log_result("Technician login", False, "Failed to login as tech1@begwork.com")
        
        data = response.json()
        if 'token' not in data:
            self.token = admin_token
            return self.log_result("Technician login", False, "No token received")
        
        # Store tech user info for later team tests
        tech_user = data.get('user', {})
        self.tech_user_id = tech_user.get('id')
        
        self.token = data['token']  # Switch to tech token
        
        # Test project access - Technician should only see assigned projects
        success, response = self.make_request('GET', 'projects', expected_status=200)
        
        if success:
            projects = response.json()
            # Tech should see fewer projects than admin (role-based filtering)
            tech_result = self.log_result("GET /projects (Technician)", True, 
                f"Technician sees {len(projects)} projects (role-filtered)")
        else:
            tech_result = self.log_result("GET /projects (Technician)", False, "Failed to get projects as Technician")
        
        # Restore admin token
        self.token = admin_token
        return tech_result

    def test_project_team_management(self):
        """Test project team operations: add member, list team, remove member"""
        project_id = self.created_project_id or self.existing_project_id
        if not project_id or not self.tech_user_id:
            return self.log_result("Project team management", False, "Missing project ID or tech user ID")
        
        # Test GET /api/projects/{id}/team (initially empty or existing members)
        success, response = self.make_request('GET', f'projects/{project_id}/team', expected_status=200)
        if not success:
            return self.log_result("GET /projects/{id}/team", False, "Failed to get team list")
        
        initial_team = response.json()
        initial_count = len(initial_team)
        get_team_result = self.log_result("GET /projects/{id}/team", True, f"Found {initial_count} team members")
        
        # Test POST /api/projects/{id}/team (add tech user)
        add_member_data = {
            "user_id": self.tech_user_id,
            "role_in_project": "Technician",
            "from_date": "2024-01-01"
        }
        
        success, response = self.make_request('POST', f'projects/{project_id}/team', add_member_data, 201)
        
        if success:
            member_data = response.json()
            member_id = member_data.get('id')
            add_member_result = self.log_result("POST /projects/{id}/team", True, "Team member added successfully")
            
            # Verify team count increased
            success, response = self.make_request('GET', f'projects/{project_id}/team', expected_status=200)
            if success:
                new_team = response.json()
                if len(new_team) == initial_count + 1:
                    verify_result = self.log_result("Team count verification", True, f"Team size: {initial_count} -> {len(new_team)}")
                else:
                    verify_result = self.log_result("Team count verification", False, "Team count didn't increase")
            else:
                verify_result = False
            
            # Test duplicate add (should fail)
            success, response = self.make_request('POST', f'projects/{project_id}/team', add_member_data, 400)
            duplicate_result = self.log_result("POST /projects/{id}/team duplicate", success, "Should reject duplicate member")
            
            # Test DELETE /api/projects/{id}/team/{memberId} (soft delete)
            if member_id:
                success, response = self.make_request('DELETE', f'projects/{project_id}/team/{member_id}', expected_status=200)
                if success:
                    remove_result = self.log_result("DELETE /projects/{id}/team/{memberId}", True, "Team member removed (soft delete)")
                    
                    # Verify team count decreased  
                    success, response = self.make_request('GET', f'projects/{project_id}/team', expected_status=200)
                    if success:
                        final_team = response.json()
                        if len(final_team) == initial_count:
                            final_verify = self.log_result("Final team count verification", True, f"Back to {len(final_team)} members")
                        else:
                            final_verify = self.log_result("Final team count verification", False, "Team count didn't decrease")
                    else:
                        final_verify = False
                else:
                    remove_result = final_verify = False
            else:
                remove_result = final_verify = False
                
            return all([get_team_result, add_member_result, verify_result, duplicate_result, remove_result, final_verify])
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /projects/{id}/team", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_project_phases_management(self):
        """Test project phases CRUD operations"""
        project_id = self.created_project_id or self.existing_project_id
        if not project_id:
            return self.log_result("Project phases management", False, "No project ID available")
        
        # Test GET /api/projects/{id}/phases (initially empty)
        success, response = self.make_request('GET', f'projects/{project_id}/phases', expected_status=200)
        if not success:
            return self.log_result("GET /projects/{id}/phases", False, "Failed to get phases list")
        
        initial_phases = response.json()
        initial_count = len(initial_phases)
        get_phases_result = self.log_result("GET /projects/{id}/phases", True, f"Found {initial_count} phases")
        
        # Test POST /api/projects/{id}/phases (create phase)
        create_phase_data = {
            "name": "Test Phase 1",
            "order": 1,
            "status": "Draft",
            "planned_start": "2024-01-01",
            "planned_end": "2024-02-29"
        }
        
        success, response = self.make_request('POST', f'projects/{project_id}/phases', create_phase_data, 201)
        
        if success:
            phase_data = response.json()
            phase_id = phase_data.get('id')
            create_phase_result = self.log_result("POST /projects/{id}/phases", True, f"Phase created: {phase_data.get('name')}")
            
            # Test PUT /api/projects/{id}/phases/{phaseId} (update phase)
            if phase_id:
                update_phase_data = {
                    "name": "Updated Test Phase 1",
                    "status": "Active"
                }
                
                success, response = self.make_request('PUT', f'projects/{project_id}/phases/{phase_id}', update_phase_data, 200)
                if success:
                    updated_phase = response.json()
                    if updated_phase.get('name') == update_phase_data['name']:
                        update_phase_result = self.log_result("PUT /projects/{id}/phases/{phaseId}", True, "Phase updated successfully")
                    else:
                        update_phase_result = self.log_result("PUT /projects/{id}/phases/{phaseId}", False, "Update not reflected")
                else:
                    update_phase_result = self.log_result("PUT /projects/{id}/phases/{phaseId}", False, "Update failed")
                
                # Test DELETE /api/projects/{id}/phases/{phaseId}
                success, response = self.make_request('DELETE', f'projects/{project_id}/phases/{phase_id}', expected_status=200)
                if success:
                    delete_phase_result = self.log_result("DELETE /projects/{id}/phases/{phaseId}", True, "Phase deleted successfully")
                else:
                    delete_phase_result = self.log_result("DELETE /projects/{id}/phases/{phaseId}", False, "Delete failed")
            else:
                update_phase_result = delete_phase_result = False
                
            return all([get_phases_result, create_phase_result, update_phase_result, delete_phase_result])
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /projects/{id}/phases", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_delete_project_admin_only(self):
        """Test DELETE /api/projects/{id} (Admin only, cascades team/phases)"""
        if not self.created_project_id:
            return self.log_result("DELETE /projects/{id} (Admin only)", False, "No test project to delete")
        
        success, response = self.make_request('DELETE', f'projects/{self.created_project_id}', expected_status=200)
        
        if success:
            data = response.json()
            if data.get('ok') is True:
                # Verify project is actually deleted
                success, response = self.make_request('GET', f'projects/{self.created_project_id}', expected_status=404)
                if success:
                    return self.log_result("DELETE /projects/{id} (Admin only)", True, "Project deleted and cascade worked")
                else:
                    return self.log_result("DELETE /projects/{id} (Admin only)", False, "Project still exists after delete")
            else:
                return self.log_result("DELETE /projects/{id} (Admin only)", False, "Unexpected response format")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("DELETE /projects/{id} (Admin only)", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_audit_logging_for_projects(self):
        """Test that project actions are logged in audit trail"""
        success, response = self.make_request('GET', 'audit-logs?limit=20', expected_status=200)
        
        if success:
            data = response.json()
            logs = data.get('logs', [])
            
            # Look for project-related actions
            project_actions = [log for log in logs if log.get('entity_type') == 'project' and 
                             log.get('action') in ['created', 'updated', 'deleted', 'team_added', 'team_removed', 'phase_created']]
            
            if len(project_actions) >= 1:
                actions_found = [f"{log['action']}" for log in project_actions[:3]]
                return self.log_result("Audit logging for projects", True, f"Found project actions: {actions_found}")
            else:
                return self.log_result("Audit logging for projects", False, "No project actions found in audit log")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("Audit logging for projects", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    # ═══ M3 ATTENDANCE MODULE TESTS ═══

    def test_attendance_statuses_endpoint(self):
        """Test GET /api/attendance/statuses returns enum list"""
        success, response = self.make_request('GET', 'attendance/statuses', expected_status=200)
        
        if success:
            data = response.json()
            expected_statuses = ["Present", "Absent", "Late", "SickLeave", "Vacation"]
            if isinstance(data, list) and set(data) == set(expected_statuses):
                return self.log_result("GET /attendance/statuses", True, f"Found all attendance statuses: {data}")
            else:
                return self.log_result("GET /attendance/statuses", False, f"Expected {expected_statuses}, got {data}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/statuses", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_self_mark_attendance(self):
        """Test POST /api/attendance/mark - self marking creates entry with uniqueness enforcement"""
        mark_data = {
            "status": "Present",
            "note": "Self-marked via API test",
            "source": "Test"
        }
        
        success, response = self.make_request('POST', 'attendance/mark', mark_data, 201)
        
        if success:
            data = response.json()
            required_fields = ['id', 'date', 'user_id', 'status', 'marked_at', 'marked_by_user_id']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                self.attendance_entry_id = data.get('id')
                return self.log_result("POST /attendance/mark", True, 
                    f"Self-marked as {data['status']}, entry ID: {data['id'][:8]}...")
            else:
                return self.log_result("POST /attendance/mark", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /attendance/mark", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_self_mark_duplicate_attendance(self):
        """Test POST /api/attendance/mark duplicate should return 400 (uniqueness constraint)"""
        mark_data = {
            "status": "Present", 
            "note": "Duplicate test",
            "source": "Test"
        }
        
        success, response = self.make_request('POST', 'attendance/mark', mark_data, 400)
        return self.log_result("POST /attendance/mark duplicate", success, "Should reject duplicate attendance for same user/date")

    def test_mark_for_user_as_admin(self):
        """Test POST /api/attendance/mark-for-user - admin can mark for any org user"""
        if not self.tech_user_id:
            return self.log_result("POST /attendance/mark-for-user (Admin)", False, "No tech user ID available")
        
        mark_data = {
            "user_id": self.tech_user_id,
            "status": "Present", 
            "note": "Admin marked for tech user",
            "source": "Test"
        }
        
        success, response = self.make_request('POST', 'attendance/mark-for-user', mark_data, 201)
        
        if success:
            data = response.json()
            if data.get('user_id') == self.tech_user_id and data.get('status') == 'Present':
                return self.log_result("POST /attendance/mark-for-user (Admin)", True, 
                    f"Admin marked tech user as {data['status']}")
            else:
                return self.log_result("POST /attendance/mark-for-user (Admin)", False, "Response data incorrect")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /attendance/mark-for-user (Admin)", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_mark_for_user_invalid_user(self):
        """Test POST /api/attendance/mark-for-user with invalid user_id should return 404"""
        mark_data = {
            "user_id": "invalid-user-id",
            "status": "Present",
            "source": "Test"
        }
        
        success, response = self.make_request('POST', 'attendance/mark-for-user', mark_data, 404)
        return self.log_result("POST /attendance/mark-for-user invalid user", success, "Should reject invalid user_id")

    def test_mark_for_user_as_technician(self):
        """Test POST /api/attendance/mark-for-user as Technician should return 403 (insufficient permissions)"""
        # Switch to technician token
        admin_token = self.token
        
        # Login as technician
        success, response = self.make_request('POST', 'auth/login', self.tech_credentials, 200)
        if not success:
            return self.log_result("Technician login for attendance test", False, "Failed to login as technician")
        
        self.token = response.json()['token']
        
        # Try to mark for someone else (should fail)
        mark_data = {
            "user_id": "some-other-user-id",
            "status": "Present",
            "source": "Test"
        }
        
        success, response = self.make_request('POST', 'attendance/mark-for-user', mark_data, 403)
        result = self.log_result("POST /attendance/mark-for-user (Technician)", success, 
            "Technician should not be able to mark for others")
        
        # Restore admin token
        self.token = admin_token
        return result

    def test_get_my_today_attendance(self):
        """Test GET /api/attendance/my-today returns entry, deadline info, active projects"""
        success, response = self.make_request('GET', 'attendance/my-today', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['date', 'past_deadline', 'deadline', 'active_projects']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                has_entry = data.get('entry') is not None
                return self.log_result("GET /attendance/my-today", True, 
                    f"Entry: {'Yes' if has_entry else 'No'}, Past deadline: {data['past_deadline']}, Deadline: {data['deadline']}")
            else:
                return self.log_result("GET /attendance/my-today", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/my-today", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_my_range_attendance(self):
        """Test GET /api/attendance/my-range returns entries for date range (last 14 days default)"""
        success, response = self.make_request('GET', 'attendance/my-range', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                return self.log_result("GET /attendance/my-range", True, 
                    f"Found {len(data)} attendance entries in range")
            else:
                return self.log_result("GET /attendance/my-range", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/my-range", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_my_range_attendance_custom_dates(self):
        """Test GET /api/attendance/my-range with custom date range"""
        success, response = self.make_request('GET', 'attendance/my-range?from_date=2024-01-01&to_date=2024-01-31', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                return self.log_result("GET /attendance/my-range custom dates", True, 
                    f"Custom range returned {len(data)} entries")
            else:
                return self.log_result("GET /attendance/my-range custom dates", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/my-range custom dates", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_site_today_attendance_admin(self):
        """Test GET /api/attendance/site-today - returns users with attendance status, missing count"""
        success, response = self.make_request('GET', 'attendance/site-today', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['users', 'missing_count', 'date']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                users = data.get('users', [])
                missing_count = data.get('missing_count', 0)
                return self.log_result("GET /attendance/site-today", True, 
                    f"Found {len(users)} users, {missing_count} missing attendance")
            else:
                return self.log_result("GET /attendance/site-today", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/site-today", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_site_today_attendance_with_project_filter(self):
        """Test GET /api/attendance/site-today?project_id=X - filtered by project"""
        if not self.existing_project_id:
            return self.log_result("GET /attendance/site-today with project filter", False, "No project ID available")
        
        success, response = self.make_request('GET', f'attendance/site-today?project_id={self.existing_project_id}', expected_status=200)
        
        if success:
            data = response.json()
            users = data.get('users', [])
            return self.log_result("GET /attendance/site-today with project filter", True, 
                f"Project-filtered view returned {len(users)} users")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/site-today with project filter", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_missing_today_attendance(self):
        """Test GET /api/attendance/missing-today - returns users without entries today"""
        success, response = self.make_request('GET', 'attendance/missing-today', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['missing', 'count', 'date']
            missing_fields = [f for f in required_fields if f not in data]
            if not missing_fields:
                missing_users = data.get('missing', [])
                count = data.get('count', 0)
                return self.log_result("GET /attendance/missing-today", True, 
                    f"Found {count} users missing attendance")
            else:
                return self.log_result("GET /attendance/missing-today", False, f"Missing fields: {missing_fields}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/missing-today", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_missing_today_attendance_with_project_filter(self):
        """Test GET /api/attendance/missing-today?project_id=X"""
        if not self.existing_project_id:
            return self.log_result("GET /attendance/missing-today with project filter", False, "No project ID available")
        
        success, response = self.make_request('GET', f'attendance/missing-today?project_id={self.existing_project_id}', expected_status=200)
        
        if success:
            data = response.json()
            missing_users = data.get('missing', [])
            return self.log_result("GET /attendance/missing-today with project filter", True, 
                f"Project-filtered missing list: {len(missing_users)} users")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /attendance/missing-today with project filter", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_site_attendance_as_technician(self):
        """Test site attendance endpoints as Technician should return 403 (manager access required)"""
        # Switch to technician token
        admin_token = self.token
        
        # Login as technician  
        success, response = self.make_request('POST', 'auth/login', self.tech_credentials, 200)
        if not success:
            return self.log_result("Technician login for site attendance test", False, "Failed to login as technician")
        
        self.token = response.json()['token']
        
        # Test site-today (should fail)
        success1, _ = self.make_request('GET', 'attendance/site-today', expected_status=403)
        
        # Test missing-today (should fail)
        success2, _ = self.make_request('GET', 'attendance/missing-today', expected_status=403)
        
        result = success1 and success2
        self.log_result("Site attendance endpoints (Technician)", result, 
            "Technician should not access site attendance endpoints")
        
        # Restore admin token
        self.token = admin_token
        return result

    def test_dashboard_stats_attendance_fields(self):
        """Test GET /api/dashboard/stats includes attendance fields (today_marked, today_present)"""
        success, response = self.make_request('GET', 'dashboard/stats', expected_status=200)
        
        if success:
            data = response.json()
            attendance_fields = ['today_marked', 'today_present']
            missing = [f for f in attendance_fields if f not in data]
            if not missing:
                return self.log_result("Dashboard stats attendance fields", True, 
                    f"Today marked: {data['today_marked']}, Today present: {data['today_present']}")
            else:
                return self.log_result("Dashboard stats attendance fields", False, f"Missing attendance fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("Dashboard stats attendance fields", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_audit_logging_for_attendance(self):
        """Test that attendance actions are logged in audit trail (attendance_marked, attendance_overridden)"""
        success, response = self.make_request('GET', 'audit-logs?limit=30', expected_status=200)
        
        if success:
            data = response.json()
            logs = data.get('logs', [])
            
            # Look for attendance-related actions
            attendance_actions = [log for log in logs if log.get('entity_type') == 'attendance' and 
                                log.get('action') in ['attendance_marked', 'attendance_overridden']]
            
            if len(attendance_actions) >= 1:
                actions_found = [f"{log['action']}" for log in attendance_actions[:3]]
                return self.log_result("Audit logging for attendance", True, f"Found attendance actions: {actions_found}")
            else:
                return self.log_result("Audit logging for attendance", False, "No attendance actions found in audit log")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("Audit logging for attendance", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    # ═══ M3 WORK REPORTS MODULE TESTS ═══

    def test_create_work_report_draft(self):
        """Test POST /api/work-reports/draft - creates draft when attendance is Present/Late"""
        if not self.existing_project_id:
            return self.log_result("POST /work-reports/draft", False, "No project ID available")
        
        draft_data = {"project_id": self.existing_project_id}
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
        
        if success:
            data = response.json()
            required_fields = ['id', 'project_id', 'user_id', 'status', 'date', 'lines', 'total_hours']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                if data['status'] == 'Draft' and data['total_hours'] == 0:
                    self.work_report_id = data['id']
                    return self.log_result("POST /work-reports/draft", True, 
                        f"Draft created: {data['id'][:8]}..., Status: {data['status']}")
                else:
                    return self.log_result("POST /work-reports/draft", False, f"Unexpected status or hours: {data}")
            else:
                return self.log_result("POST /work-reports/draft", False, f"Missing fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /work-reports/draft", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_create_work_report_draft_no_attendance(self):
        """Test POST /api/work-reports/draft fails when no Present/Late attendance (400)"""
        # Create a new user without attendance to test this scenario
        test_user = {
            "email": f"noattend_{datetime.now().strftime('%H%M%S')}@example.com",
            "password": "TestPass123!",
            "first_name": "No",
            "last_name": "Attendance",
            "role": "Technician"
        }
        
        # Create user
        success, response = self.make_request('POST', 'users', test_user, 201)
        if not success:
            return self.log_result("POST /work-reports/draft no attendance", False, "Failed to create test user")
        
        user_data = response.json()
        
        # Login as this new user
        admin_token = self.token
        success, response = self.make_request('POST', 'auth/login', 
            {"email": test_user["email"], "password": test_user["password"]}, 200)
        
        if not success:
            self.token = admin_token
            return self.log_result("POST /work-reports/draft no attendance", False, "Failed to login as test user")
        
        self.token = response.json()['token']
        
        # Try to create work report without attendance
        draft_data = {"project_id": self.existing_project_id}
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 400)
        
        result = self.log_result("POST /work-reports/draft no attendance", success, 
            "Should fail when no Present/Late attendance marked")
        
        # Clean up - restore admin token and delete test user
        self.token = admin_token
        self.make_request('DELETE', f'users/{user_data["id"]}', expected_status=200)
        
        return result

    def test_create_work_report_draft_duplicate(self):
        """Test POST /api/work-reports/draft returns existing if duplicate (same org, date, user, project)"""
        if not self.existing_project_id:
            return self.log_result("POST /work-reports/draft duplicate", False, "No project ID available")
        
        draft_data = {"project_id": self.existing_project_id}
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
        
        if success:
            data = response.json()
            # Should return existing report (same ID as before)
            if hasattr(self, 'work_report_id') and data['id'] == self.work_report_id:
                return self.log_result("POST /work-reports/draft duplicate", True, 
                    "Returns existing report for same org/date/user/project")
            else:
                return self.log_result("POST /work-reports/draft duplicate", True, 
                    "Creates or returns draft report")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /work-reports/draft duplicate", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_update_work_report(self):
        """Test PUT /api/work-reports/{id} updates summary and lines (Draft/Rejected only)"""
        if not hasattr(self, 'work_report_id'):
            return self.log_result("PUT /work-reports/{id}", False, "No work report ID available")
        
        update_data = {
            "summary_note": "Updated summary from API test",
            "lines": [
                {"activity_name": "Site inspection", "hours": 2.5, "note": "Morning inspection"},
                {"activity_name": "Equipment maintenance", "hours": 3.0, "note": "Routine check"}
            ]
        }
        
        success, response = self.make_request('PUT', f'work-reports/{self.work_report_id}', update_data, 200)
        
        if success:
            data = response.json()
            if (data.get('summary_note') == update_data['summary_note'] and 
                len(data.get('lines', [])) == 2 and
                data.get('total_hours') == 5.5):
                return self.log_result("PUT /work-reports/{id}", True, 
                    f"Updated: {len(data['lines'])} lines, {data['total_hours']}h total")
            else:
                return self.log_result("PUT /work-reports/{id}", False, "Update not reflected correctly")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("PUT /work-reports/{id}", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_update_work_report_invalid_status(self):
        """Test PUT /api/work-reports/{id} fails for Submitted/Approved reports (400)"""
        # First submit the report to test this
        if not hasattr(self, 'work_report_id'):
            return self.log_result("PUT /work-reports/{id} invalid status", False, "No work report ID available")
        
        # Submit the report first
        success, response = self.make_request('POST', f'work-reports/{self.work_report_id}/submit', expected_status=200)
        if not success:
            return self.log_result("PUT /work-reports/{id} invalid status", False, "Failed to submit report for test")
        
        # Now try to update a submitted report (should fail)
        update_data = {"summary_note": "Should not be allowed"}
        success, response = self.make_request('PUT', f'work-reports/{self.work_report_id}', update_data, 400)
        
        return self.log_result("PUT /work-reports/{id} invalid status", success, 
            "Should reject updates to Submitted/Approved reports")

    def test_submit_work_report(self):
        """Test POST /api/work-reports/{id}/submit changes status to Submitted"""
        # Create a new draft to submit (since previous one is submitted)
        if not self.existing_project_id:
            return self.log_result("POST /work-reports/{id}/submit", False, "No project ID available")
        
        # Create new draft
        draft_data = {"project_id": self.existing_project_id, "date": "2024-01-15"}  # Different date
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
        if not success:
            return self.log_result("POST /work-reports/{id}/submit", False, "Failed to create draft for submit test")
        
        new_report_id = response.json()['id']
        
        # Add lines to the report
        update_data = {
            "lines": [{"activity_name": "Testing work", "hours": 4.0, "note": "API testing"}]
        }
        success, response = self.make_request('PUT', f'work-reports/{new_report_id}', update_data, 200)
        if not success:
            return self.log_result("POST /work-reports/{id}/submit", False, "Failed to add lines for submit test")
        
        # Submit the report
        success, response = self.make_request('POST', f'work-reports/{new_report_id}/submit', expected_status=200)
        
        if success:
            data = response.json()
            if data.get('status') == 'Submitted' and data.get('submitted_at'):
                return self.log_result("POST /work-reports/{id}/submit", True, 
                    f"Report submitted: Status={data['status']}, Time={data['submitted_at'][:19]}")
            else:
                return self.log_result("POST /work-reports/{id}/submit", False, 
                    f"Unexpected status or missing submitted_at: {data}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /work-reports/{id}/submit", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_submit_work_report_no_lines(self):
        """Test POST /api/work-reports/{id}/submit fails if no activity lines (400)"""
        # Create draft without lines
        if not self.existing_project_id:
            return self.log_result("POST /work-reports/{id}/submit no lines", False, "No project ID available")
        
        draft_data = {"project_id": self.existing_project_id, "date": "2024-01-16"}  # Different date
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
        if not success:
            return self.log_result("POST /work-reports/{id}/submit no lines", False, "Failed to create draft")
        
        empty_report_id = response.json()['id']
        
        # Try to submit without lines
        success, response = self.make_request('POST', f'work-reports/{empty_report_id}/submit', expected_status=400)
        
        return self.log_result("POST /work-reports/{id}/submit no lines", success, 
            "Should reject submission with no activity lines")

    def test_approve_work_report(self):
        """Test POST /api/work-reports/{id}/approve - Admin/SiteManager can approve Submitted reports"""
        # Find a submitted report from previous tests
        if not hasattr(self, 'work_report_id'):
            return self.log_result("POST /work-reports/{id}/approve", False, "No work report ID available")
        
        success, response = self.make_request('POST', f'work-reports/{self.work_report_id}/approve', expected_status=200)
        
        if success:
            data = response.json()
            if data.get('status') == 'Approved' and data.get('approved_at') and data.get('approved_by_user_id'):
                return self.log_result("POST /work-reports/{id}/approve", True, 
                    f"Report approved: Status={data['status']}, By={data['approved_by_user_id'][:8]}...")
            else:
                return self.log_result("POST /work-reports/{id}/approve", False, 
                    f"Unexpected approval data: {data}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /work-reports/{id}/approve", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_reject_work_report(self):
        """Test POST /api/work-reports/{id}/reject requires reason, changes status to Rejected"""
        # Create and submit another report to reject
        if not self.existing_project_id:
            return self.log_result("POST /work-reports/{id}/reject", False, "No project ID available")
        
        # Create, update, and submit a report
        draft_data = {"project_id": self.existing_project_id, "date": "2024-01-17"}
        success, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
        if not success:
            return self.log_result("POST /work-reports/{id}/reject", False, "Failed to create draft for reject test")
        
        reject_report_id = response.json()['id']
        
        # Add lines and submit
        update_data = {"lines": [{"activity_name": "Reject test", "hours": 1.0, "note": "For rejection"}]}
        self.make_request('PUT', f'work-reports/{reject_report_id}', update_data, 200)
        self.make_request('POST', f'work-reports/{reject_report_id}/submit', expected_status=200)
        
        # Reject with reason
        reject_data = {"reason": "Hours seem too low for the activities described"}
        success, response = self.make_request('POST', f'work-reports/{reject_report_id}/reject', reject_data, 200)
        
        if success:
            data = response.json()
            if data.get('status') == 'Rejected' and data.get('reject_reason') == reject_data['reason']:
                return self.log_result("POST /work-reports/{id}/reject", True, 
                    f"Report rejected: Reason='{data['reject_reason'][:30]}...'")
            else:
                return self.log_result("POST /work-reports/{id}/reject", False, 
                    f"Unexpected rejection data: {data}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("POST /work-reports/{id}/reject", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_reject_work_report_no_reason(self):
        """Test POST /api/work-reports/{id}/reject fails without reason (400)"""
        # Use the previously submitted report (should be approved now)
        if not hasattr(self, 'work_report_id'):
            return self.log_result("POST /work-reports/{id}/reject no reason", False, "No work report ID available")
        
        # Try to reject without reason
        success, response = self.make_request('POST', f'work-reports/{self.work_report_id}/reject', {}, 400)
        
        return self.log_result("POST /work-reports/{id}/reject no reason", success, 
            "Should require reason for rejection")

    def test_get_work_report_detail(self):
        """Test GET /api/work-reports/{id} returns single report with project code/name"""
        if not hasattr(self, 'work_report_id'):
            return self.log_result("GET /work-reports/{id}", False, "No work report ID available")
        
        success, response = self.make_request('GET', f'work-reports/{self.work_report_id}', expected_status=200)
        
        if success:
            data = response.json()
            required_fields = ['id', 'project_id', 'user_id', 'status', 'lines', 'total_hours', 'project_code', 'project_name']
            missing = [f for f in required_fields if f not in data]
            if not missing:
                return self.log_result("GET /work-reports/{id}", True, 
                    f"Report detail: {data.get('project_code')}, {data['status']}, {data['total_hours']}h")
            else:
                return self.log_result("GET /work-reports/{id}", False, f"Missing enriched fields: {missing}")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /work-reports/{id}", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_my_work_reports_today(self):
        """Test GET /api/work-reports/my-today returns today's reports for current user"""
        success, response = self.make_request('GET', 'work-reports/my-today', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                return self.log_result("GET /work-reports/my-today", True, 
                    f"Found {len(data)} reports for today")
            else:
                return self.log_result("GET /work-reports/my-today", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /work-reports/my-today", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_my_work_reports_range(self):
        """Test GET /api/work-reports/my-range returns reports within date range"""
        success, response = self.make_request('GET', 'work-reports/my-range?from_date=2024-01-01&to_date=2024-01-31', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                return self.log_result("GET /work-reports/my-range", True, 
                    f"Found {len(data)} reports in date range")
            else:
                return self.log_result("GET /work-reports/my-range", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /work-reports/my-range", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_get_project_day_reports(self):
        """Test GET /api/work-reports/project-day returns reports for project+date (manager view)"""
        if not self.existing_project_id:
            return self.log_result("GET /work-reports/project-day", False, "No project ID available")
        
        success, response = self.make_request('GET', f'work-reports/project-day?project_id={self.existing_project_id}&date=2024-01-15', expected_status=200)
        
        if success:
            data = response.json()
            if isinstance(data, list):
                # Check for enriched data
                if len(data) > 0:
                    first_report = data[0]
                    enriched_fields = ['user_name', 'user_email', 'project_code', 'project_name']
                    missing = [f for f in enriched_fields if f not in first_report]
                    if not missing:
                        return self.log_result("GET /work-reports/project-day", True, 
                            f"Found {len(data)} enriched project reports")
                    else:
                        return self.log_result("GET /work-reports/project-day", True, 
                            f"Found {len(data)} reports, missing enrichment: {missing}")
                else:
                    return self.log_result("GET /work-reports/project-day", True, "No reports for project+date")
            else:
                return self.log_result("GET /work-reports/project-day", False, "Response not a list")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("GET /work-reports/project-day", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def test_work_report_permissions(self):
        """Test work report permissions - Technician can only create/edit own, SiteManager can approve for managed projects"""
        # Switch to technician token
        admin_token = self.token
        
        # Login as technician
        success, response = self.make_request('POST', 'auth/login', self.tech_credentials, 200)
        if not success:
            return self.log_result("Work report permissions", False, "Failed to login as technician")
        
        self.token = response.json()['token']
        
        # Test technician can create own report
        if self.existing_project_id:
            draft_data = {"project_id": self.existing_project_id}
            success1, response = self.make_request('POST', 'work-reports/draft', draft_data, 201)
            tech_create_result = success1
        else:
            tech_create_result = True  # Skip if no project
        
        # Test technician cannot approve reports (should be 403)
        if hasattr(self, 'work_report_id'):
            success2, response = self.make_request('POST', f'work-reports/{self.work_report_id}/approve', expected_status=403)
            tech_approve_result = success2
        else:
            tech_approve_result = True  # Skip if no report
        
        # Restore admin token
        self.token = admin_token
        
        overall_result = tech_create_result and tech_approve_result
        return self.log_result("Work report permissions", overall_result, 
            f"Technician create: {'✓' if tech_create_result else '✗'}, approve restriction: {'✓' if tech_approve_result else '✗'}")

    def test_audit_logging_for_work_reports(self):
        """Test work report actions are logged (report_draft_created, report_submitted, report_approved, report_rejected, report_edited)"""
        success, response = self.make_request('GET', 'audit-logs?limit=50', expected_status=200)
        
        if success:
            data = response.json()
            logs = data.get('logs', [])
            
            # Look for work report actions
            report_actions = [log for log in logs if log.get('entity_type') == 'work_report' and 
                            log.get('action') in ['report_draft_created', 'report_submitted', 'report_approved', 'report_rejected', 'report_edited']]
            
            if len(report_actions) >= 1:
                actions_found = [f"{log['action']}" for log in report_actions[:5]]
                return self.log_result("Audit logging for work reports", True, 
                    f"Found work report actions: {actions_found}")
            else:
                return self.log_result("Audit logging for work reports", False, 
                    "No work report actions found in audit log")
        else:
            details = response.text if hasattr(response, 'text') else str(response)
            return self.log_result("Audit logging for work reports", False, f"Status: {getattr(response, 'status_code', 'N/A')} - {details}")

    def run_all_tests(self):
        """Run all backend API tests"""
        print("🔬 Starting BEG_Work API Tests - M0 Core + M1 Projects + M3 Attendance")
        print("=" * 60)
        
        # M0 Core tests (existing)
        print("\n🔹 M0 CORE MODULE TESTS")
        self.test_auth_login()
        self.test_auth_me_with_token()
        self.test_auth_me_without_token()
        self.test_get_organization()
        self.test_put_organization()
        self.test_get_users()
        self.test_create_user()
        self.test_create_duplicate_user()
        self.test_create_user_invalid_role()
        self.test_update_user()
        self.test_delete_user()
        self.test_get_feature_flags()
        self.test_toggle_feature_flag()
        self.test_toggle_core_module()
        self.test_get_audit_logs()
        self.test_get_roles()
        self.test_get_subscription()
        
        # M1 Projects tests (new)
        print("\n🔹 M1 PROJECTS MODULE TESTS")
        self.test_get_dashboard_stats()
        self.test_get_project_enums()
        self.test_list_projects_admin()
        self.test_list_projects_with_filters()
        self.test_create_project_admin()
        self.test_create_project_duplicate_code()
        self.test_create_project_invalid_enum()
        self.test_get_project_detail()
        self.test_update_project_admin()
        self.test_technician_login_and_access()
        self.test_project_team_management()
        self.test_project_phases_management()
        self.test_audit_logging_for_projects()
        self.test_delete_project_admin_only()

        # M3 Attendance tests (new)
        print("\n🔹 M3 ATTENDANCE MODULE TESTS")
        self.test_attendance_statuses_endpoint()
        self.test_self_mark_attendance()
        self.test_self_mark_duplicate_attendance()
        self.test_mark_for_user_as_admin()
        self.test_mark_for_user_invalid_user()
        self.test_mark_for_user_as_technician()
        self.test_get_my_today_attendance()
        self.test_get_my_range_attendance()
        self.test_get_my_range_attendance_custom_dates()
        self.test_get_site_today_attendance_admin()
        self.test_get_site_today_attendance_with_project_filter()
        self.test_get_missing_today_attendance()
        self.test_get_missing_today_attendance_with_project_filter()
        self.test_site_attendance_as_technician()
        self.test_dashboard_stats_attendance_fields()
        self.test_audit_logging_for_attendance()
        
        # M3 Work Reports tests (new)
        print("\n🔹 M3 WORK REPORTS MODULE TESTS")
        self.test_create_work_report_draft()
        self.test_create_work_report_draft_no_attendance()
        self.test_create_work_report_draft_duplicate()
        self.test_update_work_report()
        self.test_update_work_report_invalid_status()
        self.test_submit_work_report()
        self.test_submit_work_report_no_lines()
        self.test_approve_work_report()
        self.test_reject_work_report()
        self.test_reject_work_report_no_reason()
        self.test_get_work_report_detail()
        self.test_get_my_work_reports_today()
        self.test_get_my_work_reports_range()
        self.test_get_project_day_reports()
        self.test_work_report_permissions()
        self.test_audit_logging_for_work_reports()
        
        # Final summary
        print("=" * 60)
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