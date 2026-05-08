"""
Test suite for Official Payslip feature (GET /api/payslip/{batch_id}/{worker_id})
Tests: payslip endpoint, payslip data structure, payroll tab payslip buttons, employee dossier payslip buttons
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"

# Known test data from main agent context
PAID_BATCH_ID = "c3ed7745-af58-46d7-8f58-28c81b19d7ff"
WORKER_ID = "6f69367a-e25f-489d-a7c8-f25cde6a9ac5"  # Светлин Антонов


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated requests session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestPayslipEndpoint:
    """Tests for GET /api/payslip/{batch_id}/{worker_id}"""
    
    def test_payslip_endpoint_returns_200(self, api_client):
        """Test that payslip endpoint returns 200 for valid batch/worker"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Payslip endpoint returns 200")
    
    def test_payslip_contains_worker_info(self, api_client):
        """Test that payslip contains worker information"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        # Check worker info exists
        assert "worker" in data, "Missing 'worker' field"
        worker = data["worker"]
        assert "first_name" in worker, "Missing worker first_name"
        assert "last_name" in worker, "Missing worker last_name"
        assert "hourly_rate" in worker, "Missing worker hourly_rate"
        print(f"✓ Worker info: {worker.get('first_name')} {worker.get('last_name')}, rate: {worker.get('hourly_rate')} EUR/h")
    
    def test_payslip_contains_summary(self, api_client):
        """Test that payslip contains summary with days/hours/normal/overtime/gross/net"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        # Check summary exists
        assert "summary" in data, "Missing 'summary' field"
        summary = data["summary"]
        
        required_fields = ["included_days", "total_hours", "normal_hours", "overtime_hours", "gross", "net"]
        for field in required_fields:
            assert field in summary, f"Missing summary field: {field}"
        
        print(f"✓ Summary: {summary.get('included_days')} days, {summary.get('total_hours')}h, gross: {summary.get('gross')} EUR, net: {summary.get('net')} EUR")
    
    def test_payslip_contains_by_day(self, api_client):
        """Test that payslip contains by_day breakdown"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "by_day" in data, "Missing 'by_day' field"
        by_day = data["by_day"]
        assert isinstance(by_day, list), "by_day should be a list"
        
        if len(by_day) > 0:
            day = by_day[0]
            assert "date" in day, "Missing date in by_day entry"
            assert "hours" in day, "Missing hours in by_day entry"
            print(f"✓ by_day: {len(by_day)} days, first: {day.get('date')} - {day.get('hours')}h")
        else:
            print(f"✓ by_day: empty list (no days)")
    
    def test_payslip_contains_by_project(self, api_client):
        """Test that payslip contains by_project breakdown"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "by_project" in data, "Missing 'by_project' field"
        by_project = data["by_project"]
        assert isinstance(by_project, list), "by_project should be a list"
        
        if len(by_project) > 0:
            proj = by_project[0]
            assert "project_name" in proj, "Missing project_name in by_project entry"
            assert "hours" in proj, "Missing hours in by_project entry"
            assert "value" in proj, "Missing value in by_project entry"
            print(f"✓ by_project: {len(by_project)} projects, first: {proj.get('project_name')} - {proj.get('hours')}h, {proj.get('value')} EUR")
        else:
            print(f"✓ by_project: empty list (no projects)")
    
    def test_payslip_contains_by_smr(self, api_client):
        """Test that payslip contains by_smr breakdown"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "by_smr" in data, "Missing 'by_smr' field"
        by_smr = data["by_smr"]
        assert isinstance(by_smr, list), "by_smr should be a list"
        print(f"✓ by_smr: {len(by_smr)} SMR types")
    
    def test_payslip_contains_allocations(self, api_client):
        """Test that payslip contains allocations"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "allocations" in data, "Missing 'allocations' field"
        allocations = data["allocations"]
        assert isinstance(allocations, list), "allocations should be a list"
        print(f"✓ allocations: {len(allocations)} entries")
    
    def test_payslip_contains_batch_info(self, api_client):
        """Test that payslip contains batch info (week_start, week_end, batch_status, paid_at)"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/{WORKER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "batch_id" in data, "Missing batch_id"
        assert "worker_id" in data, "Missing worker_id"
        assert "week_start" in data, "Missing week_start"
        assert "week_end" in data, "Missing week_end"
        assert "batch_status" in data, "Missing batch_status"
        
        print(f"✓ Batch info: {data.get('week_start')} → {data.get('week_end')}, status: {data.get('batch_status')}, paid_at: {data.get('paid_at')}")
    
    def test_payslip_invalid_batch_returns_error(self, api_client):
        """Test that invalid batch_id returns error"""
        response = api_client.get(f"{BASE_URL}/api/payslip/invalid-batch-id/{WORKER_ID}")
        assert response.status_code == 200  # Returns 200 with error in body
        data = response.json()
        assert "error" in data, "Expected error field for invalid batch"
        print(f"✓ Invalid batch returns error: {data.get('error')}")
    
    def test_payslip_invalid_worker_returns_error(self, api_client):
        """Test that invalid worker_id returns error"""
        response = api_client.get(f"{BASE_URL}/api/payslip/{PAID_BATCH_ID}/invalid-worker-id")
        assert response.status_code == 200  # Returns 200 with error in body
        data = response.json()
        assert "error" in data, "Expected error field for invalid worker"
        print(f"✓ Invalid worker returns error: {data.get('error')}")


class TestPayrollBatchList:
    """Tests for payroll batch list endpoint (regression)"""
    
    def test_payroll_batch_list_returns_200(self, api_client):
        """Test that payroll batch list endpoint works"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "items" in data, "Missing 'items' field"
        print(f"✓ Payroll batch list: {len(data['items'])} batches")
    
    def test_payroll_batch_detail_returns_200(self, api_client):
        """Test that payroll batch detail endpoint works"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/{PAID_BATCH_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "id" in data, "Missing 'id' field"
        assert "status" in data, "Missing 'status' field"
        assert "employee_summaries" in data, "Missing 'employee_summaries' field"
        print(f"✓ Batch detail: status={data.get('status')}, workers={len(data.get('employee_summaries', []))}")


class TestEmployeeDossier:
    """Tests for employee dossier endpoint (regression)"""
    
    def test_employee_dossier_returns_200(self, api_client):
        """Test that employee dossier endpoint works"""
        response = api_client.get(f"{BASE_URL}/api/employee-dossier/{WORKER_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check payroll weeks exist
        assert "payroll" in data, "Missing 'payroll' field"
        payroll = data["payroll"]
        assert "weeks" in payroll, "Missing 'weeks' in payroll"
        
        print(f"✓ Employee dossier: {len(payroll.get('weeks', []))} payroll weeks")


class TestSidebarNavigation:
    """Tests for sidebar navigation (legacy payroll renamed)"""
    
    def test_i18n_payroll_legacy_key_exists(self):
        """Test that i18n key for legacy payroll exists"""
        import json
        with open('/app/frontend/src/i18n/bg.json', 'r') as f:
            bg = json.load(f)
        
        assert "nav" in bg, "Missing 'nav' in i18n"
        assert "payrollLegacy" in bg["nav"], "Missing 'payrollLegacy' in nav"
        assert bg["nav"]["payrollLegacy"] == "Фишове (стар)", f"Expected 'Фишове (стар)', got '{bg['nav']['payrollLegacy']}'"
        print(f"✓ i18n payrollLegacy: '{bg['nav']['payrollLegacy']}'")


class TestPayslipI18n:
    """Tests for payslip i18n keys"""
    
    def test_payslip_i18n_keys_exist(self):
        """Test that payslip i18n keys exist"""
        import json
        with open('/app/frontend/src/i18n/bg.json', 'r') as f:
            bg = json.load(f)
        
        # Check payslip namespace exists
        assert "payslip" in bg, "Missing 'payslip' namespace in i18n"
        payslip = bg["payslip"]
        
        required_keys = ["title", "days", "hours", "normal", "overtime", "gross", "net", "byDay", "byProject", "paid", "batched"]
        for key in required_keys:
            assert key in payslip, f"Missing payslip.{key} in i18n"
        
        print(f"✓ Payslip i18n keys present: {list(payslip.keys())[:10]}...")
    
    def test_payroll_payslip_btn_key_exists(self):
        """Test that payroll.payslipBtn key exists"""
        import json
        with open('/app/frontend/src/i18n/bg.json', 'r') as f:
            bg = json.load(f)
        
        assert "payroll" in bg, "Missing 'payroll' in i18n"
        assert "payslipBtn" in bg["payroll"], "Missing 'payslipBtn' in payroll"
        print(f"✓ payroll.payslipBtn: '{bg['payroll']['payslipBtn']}'")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
