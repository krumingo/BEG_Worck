"""
Labor by SMR / Execution Package - Comprehensive Backend Tests

Tests 5 phases:
P1: Time entry linkage with labor_entries collection
P2: Planned hours engine with recompute
P3: Actual labor cost by execution package
P4: Variance + warnings
P5: Project profit integration

Project: PRJ-001 (c3529276-8c03-49b3-92de-51216aab25da)
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, date

# Test configuration
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"


class TestLaborSMRFlow:
    """End-to-end tests for Labor by SMR / Execution Package"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token for API calls"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        return resp.json()["token"]

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Headers with auth token"""
        return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 1: TIME ENTRY LINKAGE
    # ═══════════════════════════════════════════════════════════════════

    def test_p1_01_create_labor_entry_manual(self, auth_headers):
        """P1: POST /api/labor-entries creates entry with hourly_rate resolved from employee profile"""
        # First get an execution package for project
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200, f"Failed to get execution packages: {resp.text}"
        packages = resp.json()
        
        pkg_id = packages[0]["id"] if packages else None
        
        # Create a manual labor entry
        entry_data = {
            "project_id": PROJECT_ID,
            "execution_package_id": pkg_id,
            "hours": 2.5,
            "activity_name": "TEST_Manual_Entry",
            "note": "Test manual labor entry",
            "date": str(date.today()),
            "source": "manual"
        }
        resp = requests.post(f"{BASE_URL}/api/labor-entries", json=entry_data, headers=auth_headers)
        assert resp.status_code == 201, f"Failed to create labor entry: {resp.text}"
        
        created = resp.json()
        assert "id" in created, "Entry should have an ID"
        assert created["project_id"] == PROJECT_ID
        assert created["hours"] == 2.5
        assert created["source"] == "manual"
        # Note: hourly_rate may be None if employee profile doesn't have rate
        print(f"Created labor entry: id={created['id']}, hourly_rate={created.get('hourly_rate')}, labor_cost={created.get('labor_cost')}")
        
        return created["id"]

    def test_p1_02_create_labor_entry_hourly_rate_resolved(self, auth_headers):
        """P1: Verify hourly_rate is resolved from employee profile when available"""
        # Get tech1 user ID - who has hourly_rate of 16.19
        resp = requests.get(f"{BASE_URL}/api/users", headers=auth_headers)
        assert resp.status_code == 200
        users = resp.json()
        tech1_user = next((u for u in users if "tech1" in u.get("email", "")), None)
        
        if tech1_user:
            entry_data = {
                "project_id": PROJECT_ID,
                "employee_id": tech1_user["id"],
                "hours": 3,
                "activity_name": "TEST_Tech1_Entry",
                "date": str(date.today()),
                "source": "manual"
            }
            resp = requests.post(f"{BASE_URL}/api/labor-entries", json=entry_data, headers=auth_headers)
            assert resp.status_code == 201
            created = resp.json()
            
            # Check if hourly_rate was resolved
            if created.get("hourly_rate") is not None:
                print(f"Hourly rate resolved: {created['hourly_rate']} EUR/h")
                expected_cost = round(3 * created["hourly_rate"], 2)
                assert created["labor_cost"] == expected_cost, f"Labor cost should be {expected_cost}"
            else:
                # Rate not available - labor_cost should be None
                assert created["labor_cost"] is None, "labor_cost should be None when hourly_rate unavailable"
                print("No hourly_rate found in employee profile - labor_cost is None as expected")

    def test_p1_03_sync_from_work_reports(self, auth_headers):
        """P1: POST /api/labor-entries/sync-from-work-reports syncs work reports to labor_entries"""
        sync_data = {"project_id": PROJECT_ID}
        resp = requests.post(f"{BASE_URL}/api/labor-entries/sync-from-work-reports", json=sync_data, headers=auth_headers)
        assert resp.status_code == 200, f"Sync failed: {resp.text}"
        
        result = resp.json()
        assert result["ok"] is True
        assert result["project_id"] == PROJECT_ID
        print(f"Synced {result['synced']} entries from work reports")

    def test_p1_04_sync_requires_project_id(self, auth_headers):
        """P1: Sync endpoint requires project_id"""
        resp = requests.post(f"{BASE_URL}/api/labor-entries/sync-from-work-reports", json={}, headers=auth_headers)
        assert resp.status_code == 400, "Should return 400 when project_id missing"

    def test_p1_05_list_labor_entries_filter_by_project(self, auth_headers):
        """P1: GET /api/labor-entries filters by project"""
        resp = requests.get(f"{BASE_URL}/api/labor-entries?project_id={PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()
        assert isinstance(entries, list)
        
        # All entries should be for this project
        for entry in entries:
            assert entry["project_id"] == PROJECT_ID
        print(f"Found {len(entries)} labor entries for project {PROJECT_ID}")

    def test_p1_06_list_labor_entries_filter_by_execution_package(self, auth_headers):
        """P1: GET /api/labor-entries filters by execution_package_id"""
        # First get an execution package
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        if packages:
            pkg_id = packages[0]["id"]
            resp = requests.get(f"{BASE_URL}/api/labor-entries?execution_package_id={pkg_id}", headers=auth_headers)
            assert resp.status_code == 200
            entries = resp.json()
            # All returned entries should match the execution package
            for entry in entries:
                assert entry["execution_package_id"] == pkg_id
            print(f"Found {len(entries)} entries for execution package {pkg_id[:8]}...")

    def test_p1_07_list_labor_entries_filter_by_employee(self, auth_headers):
        """P1: GET /api/labor-entries filters by employee_id"""
        # Get current user
        resp = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        user = resp.json()
        
        resp = requests.get(f"{BASE_URL}/api/labor-entries?employee_id={user['id']}", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()
        for entry in entries:
            assert entry["employee_id"] == user["id"]
        print(f"Found {len(entries)} entries for employee {user['email']}")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 2: PLANNED HOURS ENGINE
    # ═══════════════════════════════════════════════════════════════════

    def test_p2_01_recompute_labor(self, auth_headers):
        """P2: POST /api/execution-packages/recompute-labor/{project_id} updates planned_hours and used_hours"""
        resp = requests.post(f"{BASE_URL}/api/execution-packages/recompute-labor/{PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200, f"Recompute failed: {resp.text}"
        
        result = resp.json()
        assert result["ok"] is True
        print(f"Recomputed labor for {result['updated']} execution packages")

    def test_p2_02_verify_packages_have_labor_fields(self, auth_headers):
        """P2: Verify execution packages have computed labor fields after recompute"""
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200
        packages = resp.json()
        
        for pkg in packages:
            # These fields should exist after recompute
            assert "planned_hours" in pkg, f"Package {pkg['id']} missing planned_hours"
            assert "used_hours" in pkg, f"Package {pkg['id']} missing used_hours"
            assert "planned_hours_source" in pkg, f"Package {pkg['id']} missing planned_hours_source"
            
            # Check planned_hours_source values
            source = pkg.get("planned_hours_source", "")
            assert source in ["offer_line", "budget_estimate", "unavailable"], f"Invalid source: {source}"
            
            print(f"Package {pkg.get('activity_name', 'N/A')[:30]}: planned={pkg.get('planned_hours')}h, used={pkg.get('used_hours')}h, source={source}")

    def test_p2_03_planned_hours_from_budget_estimate(self, auth_headers):
        """P2: Planned hours from budget estimate when labor_hours_per_unit unavailable"""
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        
        # Check for packages with budget_estimate source
        budget_estimate_pkgs = [p for p in packages if p.get("planned_hours_source") == "budget_estimate"]
        
        for pkg in budget_estimate_pkgs:
            # When using budget_estimate, planned_hours = labor_budget_total / default_rate (18 EUR/h)
            budget = pkg.get("labor_budget_total", 0)
            planned = pkg.get("planned_hours")
            if budget > 0 and planned is not None:
                # planned_hours ≈ budget / 18
                expected = round(budget / 18, 1)
                assert abs(planned - expected) < 0.5, f"Planned hours {planned} doesn't match budget estimate {expected}"
                print(f"Budget estimate working: budget={budget} EUR, planned={planned}h (expected ~{expected}h)")

    def test_p2_04_recompute_empty_project(self, auth_headers):
        """P2: Recompute on project with no packages returns gracefully"""
        fake_project_id = str(uuid.uuid4())
        resp = requests.post(f"{BASE_URL}/api/execution-packages/recompute-labor/{fake_project_id}", headers=auth_headers)
        assert resp.status_code == 200
        result = resp.json()
        assert result["ok"] is True
        assert result["updated"] == 0

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 3: ACTUAL LABOR COST BY EXECUTION PACKAGE
    # ═══════════════════════════════════════════════════════════════════

    def test_p3_01_get_labor_cost_by_execution_package(self, auth_headers):
        """P3: GET /api/labor-cost/by-execution-package/{id} returns detailed breakdown"""
        # Get an execution package
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        assert packages, "No execution packages found for testing"
        
        pkg_id = packages[0]["id"]
        resp = requests.get(f"{BASE_URL}/api/labor-cost/by-execution-package/{pkg_id}", headers=auth_headers)
        assert resp.status_code == 200, f"Failed to get labor cost: {resp.text}"
        
        result = resp.json()
        # Verify required fields
        assert result["execution_package_id"] == pkg_id
        assert "by_employee" in result, "Should have by_employee breakdown"
        assert "by_date" in result, "Should have by_date breakdown"
        assert "planned_hours" in result
        assert "used_hours" in result
        assert "remaining_hours" in result
        assert "labor_budget" in result
        assert "labor_actual_cost" in result
        assert "labor_variance" in result or result.get("labor_budget", 0) == 0
        
        print(f"Labor cost for {result.get('activity_name', 'N/A')[:30]}:")
        print(f"  - Planned: {result['planned_hours']}h, Used: {result['used_hours']}h, Remaining: {result['remaining_hours']}h")
        print(f"  - Budget: {result['labor_budget']} EUR, Actual: {result['labor_actual_cost']} EUR")
        print(f"  - By employee count: {len(result['by_employee'])}")
        print(f"  - By date count: {len(result['by_date'])}")

    def test_p3_02_labor_cost_by_employee_breakdown(self, auth_headers):
        """P3: by_employee breakdown has correct structure"""
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        if not packages:
            pytest.skip("No packages to test")
        
        pkg_id = packages[0]["id"]
        resp = requests.get(f"{BASE_URL}/api/labor-cost/by-execution-package/{pkg_id}", headers=auth_headers)
        result = resp.json()
        
        for emp in result.get("by_employee", []):
            assert "employee_id" in emp
            assert "name" in emp
            assert "hours" in emp
            assert "cost" in emp
            assert "rate" in emp

    def test_p3_03_labor_cost_by_date_breakdown(self, auth_headers):
        """P3: by_date breakdown has correct structure"""
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        if not packages:
            pytest.skip("No packages to test")
        
        pkg_id = packages[0]["id"]
        resp = requests.get(f"{BASE_URL}/api/labor-cost/by-execution-package/{pkg_id}", headers=auth_headers)
        result = resp.json()
        
        for day in result.get("by_date", []):
            assert "date" in day
            assert "hours" in day
            assert "cost" in day

    def test_p3_04_labor_cost_not_found_package(self, auth_headers):
        """P3: Returns 404 for non-existent package"""
        fake_pkg_id = str(uuid.uuid4())
        resp = requests.get(f"{BASE_URL}/api/labor-cost/by-execution-package/{fake_pkg_id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_p3_05_labor_cost_none_when_rate_unavailable(self, auth_headers):
        """P3: labor_cost = None when hourly_rate unavailable (not fabricated)"""
        # List labor entries and check for entries without hourly_rate
        resp = requests.get(f"{BASE_URL}/api/labor-entries?project_id={PROJECT_ID}", headers=auth_headers)
        entries = resp.json()
        
        for entry in entries:
            if entry.get("hourly_rate") is None:
                # If hourly_rate is None, labor_cost should also be None
                assert entry.get("labor_cost") is None, f"labor_cost should be None when hourly_rate is None: {entry['id']}"
        print("Verified: labor_cost is None when hourly_rate unavailable")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 4: VARIANCE + WARNINGS
    # ═══════════════════════════════════════════════════════════════════

    def test_p4_01_get_labor_warnings(self, auth_headers):
        """P4: GET /api/labor-warnings/{project_id} returns warnings"""
        resp = requests.get(f"{BASE_URL}/api/labor-warnings/{PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200, f"Failed to get warnings: {resp.text}"
        
        result = resp.json()
        assert result["project_id"] == PROJECT_ID
        assert "warnings" in result
        assert "packages" in result
        assert "total_entries" in result
        assert "unmapped_entries" in result
        assert "metrics_available" in result
        
        print(f"Labor warnings for project:")
        print(f"  - Total entries: {result['total_entries']}")
        print(f"  - Unmapped entries: {result['unmapped_entries']}")
        print(f"  - Warnings count: {len(result['warnings'])}")
        
        for warning in result["warnings"]:
            print(f"  - {warning['type']}: {warning['message']}")

    def test_p4_02_warning_types(self, auth_headers):
        """P4: Warnings include over_hours and over_labor_budget types"""
        resp = requests.get(f"{BASE_URL}/api/labor-warnings/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        # Check warning structure
        for warning in result["warnings"]:
            assert "type" in warning
            assert "message" in warning
            # Valid warning types
            assert warning["type"] in ["over_hours", "over_labor_budget", "unmapped_time_entries"]

    def test_p4_03_unmapped_entries_counted(self, auth_headers):
        """P4: Unmapped entries (execution_package_id=None) counted and reported"""
        resp = requests.get(f"{BASE_URL}/api/labor-warnings/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        unmapped_count = result["unmapped_entries"]
        total_count = result["total_entries"]
        
        print(f"Unmapped entries: {unmapped_count} / {total_count}")
        
        # If there are unmapped entries, there should be a warning
        if unmapped_count > 0:
            unmapped_warnings = [w for w in result["warnings"] if w["type"] == "unmapped_time_entries"]
            assert len(unmapped_warnings) > 0, "Should have unmapped_time_entries warning"

    def test_p4_04_package_summaries_in_warnings(self, auth_headers):
        """P4: Warnings endpoint returns package summaries with flags"""
        resp = requests.get(f"{BASE_URL}/api/labor-warnings/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        for pkg in result["packages"]:
            assert "id" in pkg
            assert "activity_name" in pkg
            assert "planned_hours" in pkg
            assert "used_hours" in pkg
            assert "remaining_hours" in pkg
            assert "progress_by_hours" in pkg
            assert "labor_budget" in pkg
            assert "labor_actual" in pkg
            assert "variance_value" in pkg
            assert "variance_percent" in pkg
            assert "flags" in pkg
            
            # Flags should be a list
            assert isinstance(pkg["flags"], list)

    def test_p4_05_metrics_available_flags(self, auth_headers):
        """P4: metrics_available indicates data availability"""
        resp = requests.get(f"{BASE_URL}/api/labor-warnings/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        metrics = result["metrics_available"]
        assert "labor_entries" in metrics
        assert "execution_packages" in metrics
        assert "planned_hours" in metrics
        
        print(f"Metrics available: {metrics}")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 5: PROJECT PROFIT INTEGRATION
    # ═══════════════════════════════════════════════════════════════════

    def test_p5_01_project_profit_includes_labor_detail(self, auth_headers):
        """P5: GET /api/project-profit/{id} includes labor_detail"""
        resp = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=auth_headers)
        assert resp.status_code == 200, f"Failed to get profit: {resp.text}"
        
        result = resp.json()
        assert result["project_id"] == PROJECT_ID
        
        # Check expenses section has labor_detail
        expenses = result["expenses"]
        assert "labor" in expenses
        assert "labor_hours" in expenses
        assert "labor_detail" in expenses
        
        print(f"Project profit - Labor section:")
        print(f"  - Labor cost: {expenses['labor']} EUR")
        print(f"  - Labor hours: {expenses['labor_hours']}h")

    def test_p5_02_labor_detail_structure(self, auth_headers):
        """P5: labor_detail has mapped/unmapped breakdown"""
        resp = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        labor_detail = result["expenses"].get("labor_detail")
        
        if labor_detail and labor_detail.get("has_data"):
            # Check required fields
            assert "total_hours" in labor_detail
            assert "total_cost" in labor_detail
            assert "mapped_hours" in labor_detail
            assert "mapped_cost" in labor_detail
            assert "unmapped_hours" in labor_detail
            assert "unmapped_cost" in labor_detail
            assert "budget_total" in labor_detail
            assert "planned_hours_total" in labor_detail
            assert "variance_value" in labor_detail
            assert "currency" in labor_detail
            
            print(f"Labor detail from profit:")
            print(f"  - Mapped: {labor_detail['mapped_hours']}h, {labor_detail['mapped_cost']} EUR")
            print(f"  - Unmapped: {labor_detail['unmapped_hours']}h, {labor_detail['unmapped_cost']} EUR")
            print(f"  - Budget: {labor_detail['budget_total']} EUR")
            print(f"  - Variance: {labor_detail['variance_value']} EUR")

    def test_p5_03_labor_budget_from_execution_packages(self, auth_headers):
        """P5: Labor budget_total comes from execution packages"""
        # Get packages' labor_budget_total
        resp = requests.get(f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}", headers=auth_headers)
        packages = resp.json()
        expected_budget = sum(p.get("labor_budget_total", 0) for p in packages)
        
        # Get profit summary
        resp = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        labor_detail = result["expenses"].get("labor_detail")
        if labor_detail and labor_detail.get("has_data"):
            actual_budget = labor_detail.get("budget_total", 0)
            assert abs(actual_budget - expected_budget) < 0.01, f"Budget mismatch: {actual_budget} vs {expected_budget}"
            print(f"Labor budget from execution packages: {actual_budget} EUR")

    def test_p5_04_variance_calculation(self, auth_headers):
        """P5: Variance = actual - budget (negative = under budget)"""
        resp = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        labor_detail = result["expenses"].get("labor_detail")
        if labor_detail and labor_detail.get("has_data") and labor_detail.get("budget_total", 0) > 0:
            total_cost = labor_detail["total_cost"]
            budget = labor_detail["budget_total"]
            expected_variance = round(total_cost - budget, 2)
            actual_variance = labor_detail["variance_value"]
            
            assert abs(actual_variance - expected_variance) < 0.01, f"Variance mismatch: {actual_variance} vs {expected_variance}"
            
            if actual_variance < 0:
                print(f"Project is UNDER budget by {abs(actual_variance)} EUR")
            else:
                print(f"Project is OVER budget by {actual_variance} EUR")

    def test_p5_05_metrics_available_labor_cost(self, auth_headers):
        """P5: metrics_available.labor_cost reflects real data"""
        resp = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=auth_headers)
        result = resp.json()
        
        metrics = result["metrics_available"]
        assert "labor_cost" in metrics
        
        labor_detail = result["expenses"].get("labor_detail")
        if labor_detail and labor_detail.get("has_data"):
            assert metrics["labor_cost"] is True
        print(f"Labor cost metrics available: {metrics['labor_cost']}")

    # ═══════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════

    def test_z_cleanup_test_entries(self, auth_headers):
        """Cleanup: Remove TEST_ prefixed labor entries"""
        resp = requests.get(f"{BASE_URL}/api/labor-entries?project_id={PROJECT_ID}", headers=auth_headers)
        entries = resp.json()
        
        test_entries = [e for e in entries if "TEST_" in e.get("activity_name", "")]
        print(f"Found {len(test_entries)} TEST_ labor entries to cleanup")
        
        # Note: No delete endpoint for labor_entries - they will be cleared on next sync
        # This is expected behavior - sync clears work_report_sync source entries


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
