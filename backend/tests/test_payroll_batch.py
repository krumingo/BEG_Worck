"""
Test Payroll Batch API endpoints (Sat→Fri payroll week).
Tests: eligible entries, batch creation, mark paid, list batches.
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Shared requests session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


def get_current_week_saturday():
    """Get the Saturday of the current payroll week (Sat→Fri)"""
    today = datetime.now()
    weekday = today.weekday()
    days_since_sat = (weekday - 5) % 7
    sat = today - timedelta(days=days_since_sat)
    return sat.strftime("%Y-%m-%d")


class TestPayrollBatchEligible:
    """Tests for GET /api/payroll-batch/eligible endpoint"""
    
    def test_eligible_returns_200(self, api_client):
        """GET /api/payroll-batch/eligible returns 200"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/payroll-batch/eligible returns 200")
    
    def test_eligible_response_structure(self, api_client):
        """Response has required fields: week_start, week_end, dates, workers, existing_batch, total_eligible_hours"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "week_start" in data, "Missing week_start"
        assert "week_end" in data, "Missing week_end"
        assert "dates" in data, "Missing dates"
        assert "workers" in data, "Missing workers"
        assert "existing_batch" in data or data.get("existing_batch") is None, "Missing existing_batch"
        assert "total_eligible_hours" in data, "Missing total_eligible_hours"
        
        print(f"✓ Response has required fields: week_start={data['week_start']}, week_end={data['week_end']}")
    
    def test_eligible_dates_array_has_7_days(self, api_client):
        """dates array has exactly 7 days (Sat→Fri)"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        dates = data.get("dates", [])
        assert len(dates) == 7, f"Expected 7 dates, got {len(dates)}"
        print(f"✓ dates array has 7 days: {dates}")
    
    def test_eligible_week_starts_on_saturday(self, api_client):
        """Week starts on Saturday (weekday=5)"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        week_start = data.get("week_start")
        start_date = datetime.strptime(week_start, "%Y-%m-%d")
        assert start_date.weekday() == 5, f"Expected Saturday (5), got weekday {start_date.weekday()}"
        print(f"✓ Week starts on Saturday: {week_start}")
    
    def test_eligible_week_ends_on_friday(self, api_client):
        """Week ends on Friday (weekday=4)"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        week_end = data.get("week_end")
        end_date = datetime.strptime(week_end, "%Y-%m-%d")
        assert end_date.weekday() == 4, f"Expected Friday (4), got weekday {end_date.weekday()}"
        print(f"✓ Week ends on Friday: {week_end}")
    
    def test_eligible_week_span_is_6_days(self, api_client):
        """Week span is 6 days (Sat to Fri)"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        week_start = datetime.strptime(data["week_start"], "%Y-%m-%d")
        week_end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        span = (week_end - week_start).days
        assert span == 6, f"Expected 6 days span, got {span}"
        print(f"✓ Week span is 6 days")
    
    def test_eligible_with_week_of_parameter(self, api_client):
        """week_of parameter correctly calculates containing Sat→Fri week"""
        # Test with a specific date
        test_date = "2026-01-15"  # A Wednesday
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible?week_of={test_date}")
        assert response.status_code == 200
        data = response.json()
        
        # The week containing Jan 15, 2026 (Wed) should be Sat Jan 10 → Fri Jan 16
        week_start = datetime.strptime(data["week_start"], "%Y-%m-%d")
        week_end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        test_dt = datetime.strptime(test_date, "%Y-%m-%d")
        
        assert week_start <= test_dt <= week_end, f"Test date {test_date} not in week {data['week_start']} to {data['week_end']}"
        print(f"✓ week_of={test_date} returns week {data['week_start']} to {data['week_end']}")
    
    def test_eligible_workers_structure(self, api_client):
        """Workers array has correct structure when data exists"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code == 200
        data = response.json()
        
        workers = data.get("workers", [])
        if len(workers) > 0:
            worker = workers[0]
            # Check required worker fields
            required_fields = ["worker_id", "first_name", "last_name", "days", "total_hours", "total_normal", "total_overtime", "gross", "hourly_rate"]
            for field in required_fields:
                assert field in worker, f"Worker missing field: {field}"
            
            # Check days structure
            days = worker.get("days", [])
            assert len(days) == 7, f"Expected 7 days per worker, got {len(days)}"
            
            if len(days) > 0:
                day = days[0]
                day_fields = ["date", "hours", "normal", "overtime", "entries", "has_data"]
                for field in day_fields:
                    assert field in day, f"Day missing field: {field}"
            
            print(f"✓ Worker structure is correct: {worker['first_name']} {worker['last_name']}, {worker['total_hours']}h")
        else:
            print("✓ No workers with eligible entries (structure check skipped)")
    
    def test_eligible_unauthenticated_rejected(self):
        """Unauthenticated request is rejected"""
        response = requests.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Unauthenticated request rejected")


class TestPayrollBatchCreate:
    """Tests for POST /api/payroll-batch endpoint"""
    
    def test_create_batch_requires_auth(self):
        """Create batch requires authentication"""
        response = requests.post(f"{BASE_URL}/api/payroll-batch", json={
            "week_of": get_current_week_saturday(),
            "included_days": [],
            "adjustments": []
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Create batch requires authentication")
    
    def test_create_batch_with_valid_data(self, api_client):
        """Create batch with valid data returns 200 or 409 (if already exists)"""
        # First get eligible data to find days with data
        eligible_response = api_client.get(f"{BASE_URL}/api/payroll-batch/eligible")
        assert eligible_response.status_code == 200
        eligible_data = eligible_response.json()
        
        # If batch already exists, skip creation test
        if eligible_data.get("existing_batch"):
            print(f"✓ Batch already exists for this week (status: {eligible_data['existing_batch'].get('status')}), skipping creation")
            return
        
        # Find days with data
        included_days = []
        for worker in eligible_data.get("workers", []):
            for day in worker.get("days", []):
                if day.get("has_data") and day["date"] not in included_days:
                    included_days.append(day["date"])
        
        if not included_days:
            print("✓ No eligible days with data, skipping batch creation")
            return
        
        # Create batch
        response = api_client.post(f"{BASE_URL}/api/payroll-batch", json={
            "week_of": eligible_data["week_start"],
            "included_days": included_days,
            "adjustments": []
        })
        
        # Accept 200 (created) or 409 (already exists)
        assert response.status_code in [200, 409], f"Expected 200 or 409, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            batch = response.json()
            assert "id" in batch, "Batch missing id"
            assert batch.get("status") == "batched", f"Expected status 'batched', got {batch.get('status')}"
            assert "employee_summaries" in batch, "Batch missing employee_summaries"
            assert "totals" in batch, "Batch missing totals"
            print(f"✓ Batch created: id={batch['id']}, workers={batch['totals'].get('workers')}, hours={batch['totals'].get('hours')}")
        else:
            print("✓ Batch already exists (409)")


class TestPayrollBatchList:
    """Tests for GET /api/payroll-batch/list endpoint"""
    
    def test_list_batches_returns_200(self, api_client):
        """GET /api/payroll-batch/list returns 200"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/payroll-batch/list returns 200")
    
    def test_list_batches_structure(self, api_client):
        """List batches returns items array with correct structure"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data, "Response missing 'items'"
        items = data["items"]
        assert isinstance(items, list), "items should be a list"
        
        if len(items) > 0:
            batch = items[0]
            required_fields = ["id", "week_start", "week_end", "status", "totals"]
            for field in required_fields:
                assert field in batch, f"Batch missing field: {field}"
            print(f"✓ List batches structure correct, {len(items)} batches found")
        else:
            print("✓ List batches structure correct, no batches yet")
    
    def test_list_batches_unauthenticated_rejected(self):
        """Unauthenticated request is rejected"""
        response = requests.get(f"{BASE_URL}/api/payroll-batch/list")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Unauthenticated request rejected")


class TestPayrollBatchPay:
    """Tests for POST /api/payroll-batch/{id}/pay endpoint"""
    
    def test_mark_paid_requires_auth(self):
        """Mark paid requires authentication"""
        response = requests.post(f"{BASE_URL}/api/payroll-batch/fake-id/pay", json={})
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Mark paid requires authentication")
    
    def test_mark_paid_nonexistent_batch(self, api_client):
        """Mark paid on nonexistent batch returns 404"""
        response = api_client.post(f"{BASE_URL}/api/payroll-batch/nonexistent-batch-id/pay", json={})
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Mark paid on nonexistent batch returns 404")
    
    def test_mark_paid_flow(self, api_client):
        """Test mark paid flow on existing batch"""
        # Get list of batches
        list_response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert list_response.status_code == 200
        batches = list_response.json().get("items", [])
        
        # Find a batch with status 'batched' (not yet paid)
        batched_batch = None
        for batch in batches:
            if batch.get("status") == "batched":
                batched_batch = batch
                break
        
        if not batched_batch:
            print("✓ No unpaid batches to test mark paid flow")
            return
        
        # Mark as paid
        response = api_client.post(f"{BASE_URL}/api/payroll-batch/{batched_batch['id']}/pay", json={})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("ok") == True, "Expected ok=True"
        assert data.get("status") == "paid", f"Expected status 'paid', got {data.get('status')}"
        print(f"✓ Batch {batched_batch['id']} marked as paid")
    
    def test_mark_paid_already_paid_batch(self, api_client):
        """Mark paid on already paid batch returns 400"""
        # Get list of batches
        list_response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert list_response.status_code == 200
        batches = list_response.json().get("items", [])
        
        # Find a batch with status 'paid'
        paid_batch = None
        for batch in batches:
            if batch.get("status") == "paid":
                paid_batch = batch
                break
        
        if not paid_batch:
            print("✓ No paid batches to test double-pay rejection")
            return
        
        # Try to mark as paid again
        response = api_client.post(f"{BASE_URL}/api/payroll-batch/{paid_batch['id']}/pay", json={})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print(f"✓ Double-pay rejected for batch {paid_batch['id']}")


class TestPayrollBatchGetSingle:
    """Tests for GET /api/payroll-batch/{id} endpoint"""
    
    def test_get_single_batch(self, api_client):
        """GET /api/payroll-batch/{id} returns batch details"""
        # Get list of batches
        list_response = api_client.get(f"{BASE_URL}/api/payroll-batch/list")
        assert list_response.status_code == 200
        batches = list_response.json().get("items", [])
        
        if not batches:
            print("✓ No batches to test single batch retrieval")
            return
        
        batch_id = batches[0]["id"]
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/{batch_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        batch = response.json()
        assert batch.get("id") == batch_id, "Batch ID mismatch"
        assert "employee_summaries" in batch, "Missing employee_summaries"
        assert "totals" in batch, "Missing totals"
        print(f"✓ Single batch retrieved: {batch_id}")
    
    def test_get_nonexistent_batch(self, api_client):
        """GET /api/payroll-batch/{id} returns 404 for nonexistent batch"""
        response = api_client.get(f"{BASE_URL}/api/payroll-batch/nonexistent-batch-id")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Nonexistent batch returns 404")


class TestPayrollBatchCarryForward:
    """Tests for POST /api/payroll-batch/carry-forward endpoint"""
    
    def test_carry_forward_requires_auth(self):
        """Carry forward requires authentication"""
        response = requests.post(f"{BASE_URL}/api/payroll-batch/carry-forward?week_of=2026-01-01")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Carry forward requires authentication")
    
    def test_carry_forward_requires_week_of(self, api_client):
        """Carry forward requires week_of parameter"""
        response = api_client.post(f"{BASE_URL}/api/payroll-batch/carry-forward")
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Carry forward requires week_of parameter")
    
    def test_carry_forward_with_valid_week(self, api_client):
        """Carry forward with valid week returns 200"""
        # Use a past week
        past_week = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        response = api_client.post(f"{BASE_URL}/api/payroll-batch/carry-forward?week_of={past_week}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("ok") == True, "Expected ok=True"
        assert "modified" in data, "Missing modified count"
        print(f"✓ Carry forward completed, modified={data.get('modified')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
