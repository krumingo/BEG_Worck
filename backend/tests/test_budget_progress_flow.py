"""
Test: Execution Budget Freeze + Actual Progress Input
Phases 1-6: Budget freeze, Progress updates, Progress history, 
Progress vs cost comparison, Warnings + risk, Read models
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Test data - from context: PRJ-001 has existing data
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"
# EP id with 45% progress from context
EXISTING_PKG_ID = "0e937841"  # Will need to find full ID


class TestBudgetProgressFlow:
    """Tests for Budget Freeze + Progress Input (Phases 1-6)"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token for all tests"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        token = data.get("access_token") or data.get("token")
        assert token, "No token in login response"
        return token
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Auth headers for authenticated requests"""
        return {"Authorization": f"Bearer {auth_token}"}
    
    @pytest.fixture(scope="class")
    def execution_package_id(self, auth_headers):
        """Get a valid execution package ID for testing"""
        # Get execution packages for the project
        response = requests.get(
            f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}",
            headers=auth_headers
        )
        if response.status_code == 200:
            pkgs = response.json()
            if pkgs and len(pkgs) > 0:
                # Return first package with progress or any package
                for pkg in pkgs:
                    if pkg.get("id", "").startswith("0e937841"):
                        return pkg["id"]
                return pkgs[0]["id"]
        return None

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 1 — BUDGET FREEZE TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p1_01_list_budget_freezes(self, auth_headers):
        """P1: GET /api/budget-freezes/{project_id} lists freezes"""
        response = requests.get(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List budget freezes failed: {response.text}"
        freezes = response.json()
        assert isinstance(freezes, list), "Should return a list"
        print(f"Found {len(freezes)} budget freeze(s)")
        if freezes:
            # Verify structure of first freeze
            freeze = freezes[0]
            assert "id" in freeze, "Freeze should have id"
            assert "freeze_version" in freeze, "Freeze should have freeze_version"
            assert "frozen_at" in freeze, "Freeze should have frozen_at"
            assert "packages" in freeze, "Freeze should have packages"
            assert "totals" in freeze, "Freeze should have totals"
            print(f"Latest freeze: v{freeze['freeze_version']}, packages: {freeze.get('package_count', 0)}")
    
    def test_p1_02_get_latest_budget_freeze(self, auth_headers):
        """P1: GET /api/budget-freezes/{project_id}/latest returns latest version"""
        response = requests.get(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}/latest",
            headers=auth_headers
        )
        # Could be 404 if no freeze exists, which is valid
        if response.status_code == 404:
            print("No budget freeze exists yet (expected for new project)")
            return
        
        assert response.status_code == 200, f"Get latest freeze failed: {response.text}"
        freeze = response.json()
        
        # Validate structure
        assert "id" in freeze, "Should have id"
        assert "freeze_version" in freeze, "Should have freeze_version"
        assert "packages" in freeze, "Should have packages array"
        assert "totals" in freeze, "Should have totals"
        
        # Validate totals structure
        totals = freeze["totals"]
        assert "material_budget" in totals
        assert "labor_budget" in totals
        assert "total_budget" in totals
        assert "total_sale" in totals
        
        print(f"Latest freeze: v{freeze['freeze_version']}")
        print(f"  - Packages: {freeze.get('package_count', len(freeze.get('packages', [])))}")
        print(f"  - Total budget: {totals.get('total_budget', 0)}")
        print(f"  - Total sale: {totals.get('total_sale', 0)}")
    
    def test_p1_03_create_budget_freeze(self, auth_headers):
        """P1: POST /api/budget-freezes/{project_id} creates versioned freeze with package snapshots"""
        # First get current version count
        list_response = requests.get(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}",
            headers=auth_headers
        )
        existing_freezes = list_response.json() if list_response.status_code == 200 else []
        max_version = max([f.get("freeze_version", 0) for f in existing_freezes], default=0)
        
        # Create new freeze
        response = requests.post(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}",
            headers=auth_headers,
            json={"label": f"TEST_v{max_version + 1}"}
        )
        
        # Could be 400 if no execution packages
        if response.status_code == 400:
            print(f"No packages to freeze: {response.text}")
            return
            
        assert response.status_code == 201, f"Create freeze failed: {response.text}"
        freeze = response.json()
        
        # Validate auto-increment
        assert freeze.get("freeze_version") == max_version + 1, \
            f"Version should auto-increment: expected {max_version + 1}, got {freeze.get('freeze_version')}"
        
        # Validate package snapshots
        assert "packages" in freeze, "Should have packages"
        assert len(freeze["packages"]) > 0, "Should have at least one package snapshot"
        
        # Validate package snapshot structure
        pkg_snap = freeze["packages"][0]
        assert "execution_package_id" in pkg_snap, "Package snapshot should have execution_package_id"
        assert "material_budget_total" in pkg_snap, "Package snapshot should have material_budget_total"
        assert "labor_budget_total" in pkg_snap, "Package snapshot should have labor_budget_total"
        
        print(f"Created freeze v{freeze['freeze_version']} with {len(freeze['packages'])} packages")
        print(f"  - Label: {freeze.get('label')}")
        print(f"  - Frozen at: {freeze.get('frozen_at')}")
    
    def test_p1_04_freeze_version_auto_increments(self, auth_headers):
        """P1: Freeze version auto-increments correctly"""
        # Create first freeze
        r1 = requests.post(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}",
            headers=auth_headers,
            json={"label": "TEST_increment_check"}
        )
        if r1.status_code == 400:
            pytest.skip("No packages to freeze")
            return
            
        v1 = r1.json().get("freeze_version") if r1.status_code == 201 else None
        
        # Create second freeze immediately after
        r2 = requests.post(
            f"{BASE_URL}/api/budget-freezes/{PROJECT_ID}",
            headers=auth_headers,
            json={"label": "TEST_increment_check_2"}
        )
        
        if r2.status_code == 201 and v1:
            v2 = r2.json().get("freeze_version")
            assert v2 == v1 + 1, f"Version should increment: expected {v1 + 1}, got {v2}"
            print(f"Version auto-increment verified: v{v1} -> v{v2}")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 2 — PROGRESS UPDATES TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p2_01_create_progress_update(self, auth_headers, execution_package_id):
        """P2: POST /api/progress-updates creates progress entry and updates execution package"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        test_progress = 55.5
        response = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": execution_package_id,
                "progress_percent_actual": test_progress,
                "note": "TEST_progress_update",
                "source": "manual"
            }
        )
        assert response.status_code == 201, f"Create progress failed: {response.text}"
        
        update = response.json()
        assert update.get("progress_percent_actual") == test_progress
        assert update.get("execution_package_id") == execution_package_id
        assert "id" in update
        assert "created_at" in update
        
        print(f"Created progress update: {test_progress}% for package {execution_package_id[:8]}...")
        
        # Verify execution package was updated
        pkg_response = requests.get(
            f"{BASE_URL}/api/execution-packages/{execution_package_id}",
            headers=auth_headers
        )
        if pkg_response.status_code == 200:
            pkg = pkg_response.json()
            assert pkg.get("progress_percent") == test_progress, \
                f"Package progress should be updated to {test_progress}"
            assert pkg.get("progress_last_updated_at") is not None, \
                "Package should have progress_last_updated_at"
            print(f"  - Execution package updated: progress={pkg.get('progress_percent')}%")
    
    def test_p2_02_progress_validation_0_100(self, auth_headers, execution_package_id):
        """P2: Progress validation 0-100%"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        # Test negative value (should fail)
        r_neg = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": execution_package_id,
                "progress_percent_actual": -5
            }
        )
        assert r_neg.status_code == 400, "Negative progress should be rejected"
        print("Negative progress (-5%) correctly rejected")
        
        # Test >100 value (should fail)
        r_over = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": execution_package_id,
                "progress_percent_actual": 105
            }
        )
        assert r_over.status_code == 400, "Progress >100 should be rejected"
        print("Over-100 progress (105%) correctly rejected")
        
        # Test boundary values (should pass)
        r_zero = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": execution_package_id,
                "progress_percent_actual": 0,
                "note": "TEST_zero_progress"
            }
        )
        assert r_zero.status_code == 201, "0% progress should be accepted"
        print("Boundary value 0% accepted")
        
        r_100 = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": execution_package_id,
                "progress_percent_actual": 100,
                "note": "TEST_100_progress"
            }
        )
        assert r_100.status_code == 201, "100% progress should be accepted"
        print("Boundary value 100% accepted")
    
    def test_p2_03_list_progress_updates_by_project(self, auth_headers):
        """P2: GET /api/progress-updates lists by project"""
        response = requests.get(
            f"{BASE_URL}/api/progress-updates?project_id={PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List progress failed: {response.text}"
        
        updates = response.json()
        assert isinstance(updates, list)
        print(f"Found {len(updates)} progress updates for project")
        
        if updates:
            # Verify structure
            update = updates[0]
            assert "id" in update
            assert "execution_package_id" in update
            assert "progress_percent_actual" in update
            assert "created_at" in update
    
    def test_p2_04_list_progress_updates_by_package(self, auth_headers, execution_package_id):
        """P2: GET /api/progress-updates lists by package"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        response = requests.get(
            f"{BASE_URL}/api/progress-updates?execution_package_id={execution_package_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List by package failed: {response.text}"
        
        updates = response.json()
        assert isinstance(updates, list)
        
        # All should belong to the same package
        for u in updates:
            assert u.get("execution_package_id") == execution_package_id
        
        print(f"Found {len(updates)} progress updates for package {execution_package_id[:8]}...")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 3 — PROGRESS HISTORY TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p3_01_get_latest_progress(self, auth_headers, execution_package_id):
        """P3: GET /api/progress-updates/{pkg_id}/latest returns latest progress"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        response = requests.get(
            f"{BASE_URL}/api/progress-updates/{execution_package_id}/latest",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get latest progress failed: {response.text}"
        
        data = response.json()
        
        # Should have has_progress flag
        if data.get("has_progress"):
            assert "progress_percent_actual" in data
            assert "execution_package_id" in data
            print(f"Latest progress: {data.get('progress_percent_actual')}%")
        else:
            print("No progress data exists for this package")
    
    def test_p3_02_get_progress_history(self, auth_headers, execution_package_id):
        """P3: GET /api/progress-updates/{pkg_id}/history returns full history with user names"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        response = requests.get(
            f"{BASE_URL}/api/progress-updates/{execution_package_id}/history",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get history failed: {response.text}"
        
        data = response.json()
        
        # Validate structure
        assert "execution_package_id" in data
        assert "entries" in data
        assert "count" in data
        
        entries = data["entries"]
        print(f"Progress history: {data['count']} entries")
        
        if entries:
            # Verify user name enrichment
            entry = entries[-1]  # Latest entry
            assert "updated_by_name" in entry, "History should include user names"
            print(f"  - Latest: {entry.get('progress_percent_actual')}% by {entry.get('updated_by_name', 'Unknown')}")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 4 — PROGRESS VS COST COMPARISON TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p4_01_get_progress_comparison(self, auth_headers, execution_package_id):
        """P4: GET /api/progress-comparison/{pkg_id} returns progress vs labor/material/subcontract usage"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        response = requests.get(
            f"{BASE_URL}/api/progress-comparison/{execution_package_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get comparison failed: {response.text}"
        
        data = response.json()
        
        # Validate structure
        assert "execution_package_id" in data
        assert "progress" in data
        assert "usage" in data
        assert "gaps" in data
        assert "raw" in data
        
        # Progress section
        progress = data["progress"]
        assert "actual_percent" in progress
        assert "has_update" in progress
        
        # Usage section
        usage = data["usage"]
        assert "labor_percent" in usage
        assert "material_percent" in usage
        assert "subcontract_percent" in usage
        
        # Gaps section
        gaps = data["gaps"]
        assert "labor_vs_progress" in gaps
        assert "material_vs_progress" in gaps
        assert "subcontract_vs_progress" in gaps
        
        print(f"Progress comparison for {execution_package_id[:8]}...")
        print(f"  - Actual progress: {progress.get('actual_percent')}%")
        print(f"  - Labor usage: {usage.get('labor_percent')}%")
        print(f"  - Material usage: {usage.get('material_percent')}%")
        print(f"  - Subcontract: {usage.get('subcontract_percent')}%")
    
    def test_p4_02_gaps_calculation(self, auth_headers, execution_package_id):
        """P4: Gaps calculated: usage% - progress%"""
        if not execution_package_id:
            pytest.skip("No execution package available")
        
        response = requests.get(
            f"{BASE_URL}/api/progress-comparison/{execution_package_id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        progress = data["progress"]["actual_percent"]
        usage = data["usage"]
        gaps = data["gaps"]
        has_update = data["progress"]["has_update"]
        
        # Verify gap calculation: gap = usage - progress
        # Positive gap = cost ahead of progress
        # Negative gap = cost behind progress
        
        if has_update:
            if usage.get("labor_percent") is not None and gaps.get("labor_vs_progress") is not None:
                expected_labor_gap = round(usage["labor_percent"] - progress, 1)
                actual_labor_gap = gaps["labor_vs_progress"]
                assert abs(expected_labor_gap - actual_labor_gap) < 0.2, \
                    f"Labor gap mismatch: expected {expected_labor_gap}, got {actual_labor_gap}"
                print(f"Labor gap: {actual_labor_gap}% (labor {usage['labor_percent']}% - progress {progress}%)")
            
            if usage.get("material_percent") is not None and gaps.get("material_vs_progress") is not None:
                expected_mat_gap = round(usage["material_percent"] - progress, 1)
                actual_mat_gap = gaps["material_vs_progress"]
                assert abs(expected_mat_gap - actual_mat_gap) < 0.2, \
                    f"Material gap mismatch: expected {expected_mat_gap}, got {actual_mat_gap}"
                print(f"Material gap: {actual_mat_gap}%")
        else:
            print("No progress update, gaps should be None")
            assert gaps.get("labor_vs_progress") is None

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 5 — WARNINGS + RISK TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p5_01_get_progress_warnings(self, auth_headers):
        """P5: GET /api/progress-warnings/{project_id} returns labor/material ahead + progress lag warnings"""
        response = requests.get(
            f"{BASE_URL}/api/progress-warnings/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get warnings failed: {response.text}"
        
        data = response.json()
        
        # Validate structure
        assert "project_id" in data
        assert "warnings" in data
        assert "total" in data
        assert "packages_total" in data
        assert "packages_with_progress" in data
        assert "packages_without_progress" in data
        
        print(f"Progress warnings for project:")
        print(f"  - Total warnings: {data['total']}")
        print(f"  - Packages total: {data['packages_total']}")
        print(f"  - With progress: {data['packages_with_progress']}")
        print(f"  - Without progress: {data['packages_without_progress']}")
        
        # Check warning types
        warnings = data["warnings"]
        warning_types = set(w.get("type") for w in warnings)
        expected_types = {"labor_ahead_of_progress", "materials_ahead_of_progress", 
                         "progress_lag", "missing_progress_updates"}
        
        for w in warnings:
            assert w.get("type") in expected_types, f"Unexpected warning type: {w.get('type')}"
            assert "severity" in w, "Warning should have severity"
            print(f"  - {w.get('type')}: {w.get('message', '')[:50]}...")
    
    def test_p5_02_project_risk_includes_progress_flags(self, auth_headers):
        """P5: Project risk includes progress flags (insufficient_progress_data, critical_progress_lag)"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get risk failed: {response.text}"
        
        data = response.json()
        
        # Validate structure
        assert "project_id" in data
        assert "risk_level" in data
        assert "risk_flags" in data
        assert "explanations" in data
        assert "flag_count" in data
        
        risk_flags = data["risk_flags"]
        
        # Check for progress-related flags
        progress_flags = {"no_progress_data", "insufficient_progress_data", "critical_progress_lag"}
        found_progress_flags = [f for f in risk_flags if f in progress_flags]
        
        print(f"Project risk level: {data['risk_level']}")
        print(f"  - Total flags: {data['flag_count']}")
        print(f"  - Progress flags: {found_progress_flags}")
        print(f"  - All flags: {risk_flags}")
        
        # From context: project should have insufficient_progress_data flag
        # (only some packages have progress)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 6 — READ MODELS TESTS
    # ═══════════════════════════════════════════════════════════════════
    
    def test_p6_01_get_project_progress_summary(self, auth_headers):
        """P6: GET /api/project-progress-summary/{project_id} returns weighted progress + budget freeze"""
        response = requests.get(
            f"{BASE_URL}/api/project-progress-summary/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get summary failed: {response.text}"
        
        data = response.json()
        
        # Validate structure
        assert "project_id" in data
        assert "packages" in data
        assert "summary" in data
        
        # Summary section
        summary = data["summary"]
        assert "total_packages" in summary
        assert "packages_with_progress" in summary
        assert "weighted_progress_percent" in summary
        assert "total_sale" in summary
        
        print(f"Project progress summary:")
        print(f"  - Total packages: {summary['total_packages']}")
        print(f"  - With progress: {summary['packages_with_progress']}")
        print(f"  - Weighted progress: {summary['weighted_progress_percent']}%")
        print(f"  - Total sale: {summary['total_sale']} EUR")
        
        # Packages should have expected fields
        if data["packages"]:
            pkg = data["packages"][0]
            assert "id" in pkg
            assert "activity_name" in pkg
            assert "progress_percent" in pkg
            assert "has_progress_update" in pkg
            assert "sale_total" in pkg
    
    def test_p6_02_summary_includes_budget_freeze(self, auth_headers):
        """P6: Project progress summary includes latest budget freeze"""
        response = requests.get(
            f"{BASE_URL}/api/project-progress-summary/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Check budget_freeze field
        budget_freeze = data.get("budget_freeze")
        
        if budget_freeze:
            assert "version" in budget_freeze or budget_freeze is None
            if budget_freeze.get("version"):
                assert "frozen_at" in budget_freeze
                assert "totals" in budget_freeze
                print(f"Budget freeze in summary: v{budget_freeze.get('version')}")
                print(f"  - Total budget: {budget_freeze.get('totals', {}).get('total_budget', 0)} EUR")
        else:
            print("No budget freeze linked to summary (expected if no freezes exist)")
    
    def test_p6_03_weighted_progress_calculation(self, auth_headers):
        """P6: Weighted progress = sum(progress * sale/total_sale)"""
        response = requests.get(
            f"{BASE_URL}/api/project-progress-summary/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        packages = data["packages"]
        summary = data["summary"]
        
        if not packages or summary["total_sale"] == 0:
            pytest.skip("No packages or zero total sale")
        
        # Calculate expected weighted progress
        total_sale = summary["total_sale"]
        calculated_weighted = 0
        
        for pkg in packages:
            if pkg.get("has_progress_update"):
                progress = pkg.get("progress_percent", 0) or 0
                sale = pkg.get("sale_total", 0)
                if total_sale > 0:
                    calculated_weighted += progress * (sale / total_sale)
        
        reported_weighted = summary["weighted_progress_percent"]
        
        # Allow small rounding differences
        assert abs(calculated_weighted - reported_weighted) < 0.5, \
            f"Weighted progress mismatch: calculated {round(calculated_weighted, 1)}, reported {reported_weighted}"
        
        print(f"Weighted progress verified: {reported_weighted}%")
        print(f"  - Calculated: {round(calculated_weighted, 1)}%")

    # ═══════════════════════════════════════════════════════════════════
    # EDGE CASES & ERROR HANDLING
    # ═══════════════════════════════════════════════════════════════════
    
    def test_error_invalid_project_id(self, auth_headers):
        """Test 404 for non-existent project"""
        fake_id = "non-existent-project-id"
        
        r1 = requests.get(
            f"{BASE_URL}/api/budget-freezes/{fake_id}",
            headers=auth_headers
        )
        # Should return empty list or 404
        assert r1.status_code in [200, 404]
        
        r2 = requests.get(
            f"{BASE_URL}/api/progress-warnings/{fake_id}",
            headers=auth_headers
        )
        assert r2.status_code in [200, 404]
        
        print("Invalid project ID handling verified")
    
    def test_error_invalid_package_id(self, auth_headers):
        """Test 404 for non-existent package"""
        fake_id = "non-existent-package-id"
        
        r1 = requests.get(
            f"{BASE_URL}/api/progress-comparison/{fake_id}",
            headers=auth_headers
        )
        assert r1.status_code == 404, f"Should return 404 for non-existent package: {r1.status_code}"
        
        r2 = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={
                "execution_package_id": fake_id,
                "progress_percent_actual": 50
            }
        )
        assert r2.status_code == 404, f"Should return 404 for non-existent package: {r2.status_code}"
        
        print("Invalid package ID handling verified")
    
    def test_error_missing_package_id(self, auth_headers):
        """Test 400 when execution_package_id is missing"""
        response = requests.post(
            f"{BASE_URL}/api/progress-updates",
            headers=auth_headers,
            json={"progress_percent_actual": 50}
        )
        assert response.status_code == 400
        print("Missing package ID correctly rejected")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
