"""
M4 HR/Payroll Module Tests
Tests for: Employee profiles, Advances/Loans, Payroll Runs, Payslips
"""
import pytest
import requests
import os
import uuid

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_TECH_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD
TECH_EMAIL = "tech2@begwork.com"
TECH_PASSWORD = VALID_TECH_PASSWORD


class TestSetup:
    """Setup and utility methods"""
    
    @staticmethod
    def login(email, password):
        """Login and return token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": password
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["token"]

    @staticmethod
    def get_headers(token):
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }


@pytest.fixture(scope="module")
def admin_token():
    """Get admin token"""
    return TestSetup.login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def tech_token():
    """Get technician token"""
    return TestSetup.login(TECH_EMAIL, TECH_PASSWORD)


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return TestSetup.get_headers(admin_token)


@pytest.fixture(scope="module")
def tech_headers(tech_token):
    return TestSetup.get_headers(tech_token)


class TestEmployeeProfiles:
    """Test employee profile endpoints"""
    
    def test_list_employees(self, admin_headers):
        """GET /api/employees - Lists employees with profile info"""
        response = requests.get(f"{BASE_URL}/api/employees", headers=admin_headers)
        assert response.status_code == 200
        employees = response.json()
        assert isinstance(employees, list)
        # Should have at least some employees
        if len(employees) > 0:
            emp = employees[0]
            assert "id" in emp
            assert "email" in emp
            assert "role" in emp
            assert "profile" in emp  # profile field exists (can be null)
        print(f"Found {len(employees)} employees")
    
    def test_create_update_employee_profile(self, admin_headers):
        """POST /api/employees - Creates/updates employee profile with pay type and rate"""
        # First get an employee to update
        response = requests.get(f"{BASE_URL}/api/employees", headers=admin_headers)
        employees = response.json()
        
        # Find a non-admin employee
        target = None
        for emp in employees:
            if emp["role"] == "Technician":
                target = emp
                break
        
        if not target:
            pytest.skip("No technician found to test profile update")
        
        # Create/update profile with Daily pay type
        profile_data = {
            "user_id": target["id"],
            "pay_type": "Daily",
            "daily_rate": 120.0,
            "standard_hours_per_day": 8,
            "pay_schedule": "Monthly",
            "active": True,
            "start_date": "2025-01-01"
        }
        response = requests.post(f"{BASE_URL}/api/employees", json=profile_data, headers=admin_headers)
        assert response.status_code == 201
        
        profile = response.json()
        assert profile["user_id"] == target["id"]
        assert profile["pay_type"] == "Daily"
        assert profile["daily_rate"] == 120.0
        assert profile["active"] == True
        print(f"Created/updated profile for {target['email']}")
    
    def test_technician_cannot_list_employees(self, tech_headers):
        """Technician should not have access to /api/employees"""
        response = requests.get(f"{BASE_URL}/api/employees", headers=tech_headers)
        assert response.status_code == 403
        print("Correctly denied technician access to employees list")


class TestAdvances:
    """Test advances/loans endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self, admin_headers):
        self.admin_headers = admin_headers
        # Get a technician user ID for testing
        response = requests.get(f"{BASE_URL}/api/employees", headers=admin_headers)
        employees = response.json()
        for emp in employees:
            if emp["role"] == "Technician":
                self.tech_user_id = emp["id"]
                break
        else:
            self.tech_user_id = None
    
    def test_list_advances(self, admin_headers):
        """GET /api/advances - Lists advances with filters"""
        response = requests.get(f"{BASE_URL}/api/advances", headers=admin_headers)
        assert response.status_code == 200
        advances = response.json()
        assert isinstance(advances, list)
        print(f"Found {len(advances)} advances")
    
    def test_list_advances_filter_status(self, admin_headers):
        """GET /api/advances?status=Open - Filter by status"""
        response = requests.get(f"{BASE_URL}/api/advances?status=Open", headers=admin_headers)
        assert response.status_code == 200
        advances = response.json()
        # All returned advances should have status=Open
        for adv in advances:
            assert adv["status"] == "Open"
        print(f"Found {len(advances)} Open advances")
    
    def test_create_advance(self, admin_headers):
        """POST /api/advances - Creates advance/loan for employee"""
        if not self.tech_user_id:
            pytest.skip("No technician found for advance test")
        
        advance_data = {
            "user_id": self.tech_user_id,
            "type": "Advance",
            "amount": 100.0,
            "currency": "EUR",
            "issued_date": "2025-01-15",
            "note": "TEST_advance - Will be cleaned up"
        }
        response = requests.post(f"{BASE_URL}/api/advances", json=advance_data, headers=admin_headers)
        assert response.status_code == 201
        
        advance = response.json()
        assert advance["user_id"] == self.tech_user_id
        assert advance["type"] == "Advance"
        assert advance["amount"] == 100.0
        assert advance["remaining_amount"] == 100.0
        assert advance["status"] == "Open"
        print(f"Created advance {advance['id']}")
    
    def test_technician_can_view_own_advances(self, tech_headers):
        """Technicians can view their own advances"""
        response = requests.get(f"{BASE_URL}/api/advances", headers=tech_headers)
        # Technicians should be able to see advances (their own only)
        assert response.status_code == 200


class TestPayrollRuns:
    """Test payroll run endpoints"""
    
    test_run_id = None
    
    def test_list_payroll_runs(self, admin_headers):
        """GET /api/payroll-runs - Lists payroll runs"""
        response = requests.get(f"{BASE_URL}/api/payroll-runs", headers=admin_headers)
        assert response.status_code == 200
        runs = response.json()
        assert isinstance(runs, list)
        print(f"Found {len(runs)} payroll runs")
    
    def test_create_payroll_run(self, admin_headers):
        """POST /api/payroll-runs - Creates draft payroll run"""
        run_data = {
            "period_type": "Monthly",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31"
        }
        response = requests.post(f"{BASE_URL}/api/payroll-runs", json=run_data, headers=admin_headers)
        assert response.status_code == 201
        
        run = response.json()
        assert run["period_type"] == "Monthly"
        assert run["period_start"] == "2025-01-01"
        assert run["period_end"] == "2025-01-31"
        assert run["status"] == "Draft"
        TestPayrollRuns.test_run_id = run["id"]
        print(f"Created payroll run {run['id']}")
    
    def test_get_payroll_run(self, admin_headers):
        """GET /api/payroll-runs/{id} - Get single payroll run with payslips"""
        if not TestPayrollRuns.test_run_id:
            pytest.skip("No test run created")
        
        response = requests.get(f"{BASE_URL}/api/payroll-runs/{TestPayrollRuns.test_run_id}", headers=admin_headers)
        assert response.status_code == 200
        
        run = response.json()
        assert run["id"] == TestPayrollRuns.test_run_id
        assert "payslips" in run
    
    def test_generate_payslips(self, admin_headers):
        """POST /api/payroll-runs/{id}/generate - Creates payslips for active employees"""
        if not TestPayrollRuns.test_run_id:
            pytest.skip("No test run created")
        
        response = requests.post(f"{BASE_URL}/api/payroll-runs/{TestPayrollRuns.test_run_id}/generate", headers=admin_headers)
        assert response.status_code == 200
        
        result = response.json()
        assert result["ok"] == True
        print(f"Generated payslips: created={result.get('created')}, updated={result.get('updated')}")
    
    def test_finalize_payroll(self, admin_headers):
        """POST /api/payroll-runs/{id}/finalize - Locks payroll"""
        if not TestPayrollRuns.test_run_id:
            pytest.skip("No test run created")
        
        response = requests.post(f"{BASE_URL}/api/payroll-runs/{TestPayrollRuns.test_run_id}/finalize", headers=admin_headers)
        assert response.status_code == 200
        
        run = response.json()
        assert run["status"] == "Finalized"
        print("Payroll finalized successfully")


class TestPayslips:
    """Test payslip endpoints"""
    
    def test_list_payslips_admin(self, admin_headers):
        """Admin can list all payslips"""
        response = requests.get(f"{BASE_URL}/api/payslips", headers=admin_headers)
        assert response.status_code == 200
        payslips = response.json()
        assert isinstance(payslips, list)
        print(f"Admin found {len(payslips)} payslips")
    
    def test_technician_sees_only_own_payslips(self, tech_headers, tech_token):
        """Technician can only view own payslips via /api/payslips"""
        response = requests.get(f"{BASE_URL}/api/payslips", headers=tech_headers)
        assert response.status_code == 200
        payslips = response.json()
        
        # Get tech user info
        me_response = requests.get(f"{BASE_URL}/api/auth/me", headers=tech_headers)
        tech_user_id = me_response.json()["id"]
        
        # All payslips should belong to the tech user
        for ps in payslips:
            assert ps["user_id"] == tech_user_id, "Technician should only see own payslips"
        print(f"Technician sees {len(payslips)} own payslips")


class TestSetDeductions:
    """Test payslip deductions editing"""
    
    def test_set_deductions_on_draft_payroll(self, admin_headers):
        """POST /api/payslips/{id}/set-deductions - Works only for draft payroll"""
        # Create a new draft payroll run for this test
        run_data = {
            "period_type": "Monthly",
            "period_start": "2025-02-01",
            "period_end": "2025-02-28"
        }
        create_response = requests.post(f"{BASE_URL}/api/payroll-runs", json=run_data, headers=admin_headers)
        assert create_response.status_code == 201
        run_id = create_response.json()["id"]
        
        # Generate payslips
        gen_response = requests.post(f"{BASE_URL}/api/payroll-runs/{run_id}/generate", headers=admin_headers)
        assert gen_response.status_code == 200
        
        # Get the payslips
        run_response = requests.get(f"{BASE_URL}/api/payroll-runs/{run_id}", headers=admin_headers)
        payslips = run_response.json().get("payslips", [])
        
        if not payslips:
            # Delete the test run
            requests.delete(f"{BASE_URL}/api/payroll-runs/{run_id}", headers=admin_headers)
            pytest.skip("No payslips generated")
        
        payslip_id = payslips[0]["id"]
        
        # Set deductions on draft payroll (should work)
        ded_response = requests.post(f"{BASE_URL}/api/payslips/{payslip_id}/set-deductions", 
            json={"deductions_amount": 50.0, "advances_to_deduct": []},
            headers=admin_headers
        )
        assert ded_response.status_code == 200
        updated = ded_response.json()
        assert updated["deductions_amount"] == 50.0
        print("Set deductions on draft payslip - OK")
        
        # Now finalize the payroll
        fin_response = requests.post(f"{BASE_URL}/api/payroll-runs/{run_id}/finalize", headers=admin_headers)
        assert fin_response.status_code == 200
        
        # Try to set deductions again (should fail)
        ded_response2 = requests.post(f"{BASE_URL}/api/payslips/{payslip_id}/set-deductions",
            json={"deductions_amount": 100.0, "advances_to_deduct": []},
            headers=admin_headers
        )
        assert ded_response2.status_code == 400
        assert "Draft" in ded_response2.json().get("detail", "")
        print("Correctly blocked deduction edit on finalized payroll")


class TestMarkPaid:
    """Test mark paid functionality"""
    
    def test_mark_paid_on_finalized_payroll(self, admin_headers):
        """POST /api/payslips/{id}/mark-paid - Works only for finalized payroll"""
        # Find a finalized payroll with unpaid payslips
        runs_response = requests.get(f"{BASE_URL}/api/payroll-runs?status=Finalized", headers=admin_headers)
        runs = runs_response.json()
        
        target_payslip_id = None
        for run in runs:
            run_detail = requests.get(f"{BASE_URL}/api/payroll-runs/{run['id']}", headers=admin_headers)
            payslips = run_detail.json().get("payslips", [])
            for ps in payslips:
                if ps["status"] == "Finalized":
                    target_payslip_id = ps["id"]
                    break
            if target_payslip_id:
                break
        
        if not target_payslip_id:
            pytest.skip("No finalized unpaid payslip found")
        
        # Mark as paid
        pay_response = requests.post(f"{BASE_URL}/api/payslips/{target_payslip_id}/mark-paid",
            json={"method": "Cash"},
            headers=admin_headers
        )
        assert pay_response.status_code == 200
        paid_slip = pay_response.json()
        assert paid_slip["status"] == "Paid"
        assert paid_slip["paid_at"] is not None
        print(f"Marked payslip {target_payslip_id} as paid")
    
    def test_cannot_mark_paid_on_draft(self, admin_headers):
        """Cannot mark paid on draft payroll"""
        # Create draft run
        run_data = {
            "period_type": "Monthly",
            "period_start": "2025-03-01",
            "period_end": "2025-03-31"
        }
        create_response = requests.post(f"{BASE_URL}/api/payroll-runs", json=run_data, headers=admin_headers)
        run_id = create_response.json()["id"]
        
        # Generate payslips
        gen_response = requests.post(f"{BASE_URL}/api/payroll-runs/{run_id}/generate", headers=admin_headers)
        
        # Get payslips
        run_response = requests.get(f"{BASE_URL}/api/payroll-runs/{run_id}", headers=admin_headers)
        payslips = run_response.json().get("payslips", [])
        
        if payslips:
            payslip_id = payslips[0]["id"]
            # Try to mark paid (should fail)
            pay_response = requests.post(f"{BASE_URL}/api/payslips/{payslip_id}/mark-paid",
                json={"method": "Cash"},
                headers=admin_headers
            )
            assert pay_response.status_code == 400
            print("Correctly blocked mark-paid on draft payroll")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/payroll-runs/{run_id}", headers=admin_headers)


class TestPayrollCalculations:
    """Test payroll calculation logic"""
    
    def test_daily_rate_calculation(self, admin_headers):
        """Daily pay = days_present * daily_rate"""
        # Find an employee with daily pay type
        employees_response = requests.get(f"{BASE_URL}/api/employees", headers=admin_headers)
        employees = employees_response.json()
        
        daily_emp = None
        for emp in employees:
            if emp.get("profile") and emp["profile"].get("pay_type") == "Daily":
                daily_emp = emp
                break
        
        if not daily_emp:
            pytest.skip("No daily pay employee found")
        
        profile = daily_emp["profile"]
        daily_rate = profile.get("daily_rate", 0)
        print(f"Found daily employee {daily_emp['email']} with rate {daily_rate}")
        
        # Look for their payslips
        payslips_response = requests.get(f"{BASE_URL}/api/payslips?user_id={daily_emp['id']}", headers=admin_headers)
        payslips = payslips_response.json()
        
        for ps in payslips:
            details = ps.get("details_json", {})
            if details.get("pay_type") == "Daily" and details.get("days_present") is not None:
                expected = details["days_present"] * details.get("daily_rate", 0)
                assert abs(ps["base_amount"] - expected) < 0.01, f"Daily calc mismatch: {ps['base_amount']} != {expected}"
                print(f"Daily calculation verified: {details['days_present']} days * {details['daily_rate']} = {ps['base_amount']}")
                break


class TestEnums:
    """Test payroll enums endpoint"""
    
    def test_get_payroll_enums(self, admin_headers):
        """GET /api/payroll-enums returns all payroll-related enums"""
        response = requests.get(f"{BASE_URL}/api/payroll-enums", headers=admin_headers)
        assert response.status_code == 200
        
        enums = response.json()
        assert "pay_types" in enums
        assert "Hourly" in enums["pay_types"]
        assert "Daily" in enums["pay_types"]
        assert "Monthly" in enums["pay_types"]
        assert "advance_types" in enums
        assert "payroll_statuses" in enums
        print("Payroll enums verified")


class TestCleanup:
    """Cleanup test data"""
    
    def test_cleanup_test_payroll_runs(self, admin_headers):
        """Delete test payroll runs"""
        runs_response = requests.get(f"{BASE_URL}/api/payroll-runs", headers=admin_headers)
        runs = runs_response.json()
        
        deleted = 0
        for run in runs:
            # Only delete draft runs created during tests (recent runs with specific periods)
            if run["status"] == "Draft" and run["period_start"] in ["2025-01-01", "2025-02-01", "2025-03-01"]:
                del_response = requests.delete(f"{BASE_URL}/api/payroll-runs/{run['id']}", headers=admin_headers)
                if del_response.status_code == 200:
                    deleted += 1
        
        print(f"Cleaned up {deleted} test payroll runs")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
