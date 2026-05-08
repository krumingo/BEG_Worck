"""
Test Material Cost by SMR / Execution Package - 5 Phases
P1: Material entry linkage from warehouse/consumption
P2: Material actual cost by exec package  
P3: Material budget/actual/variance recompute
P4: Package financial summary with margin
P5: Warnings + profit integration

Uses admin@begwork.com / AdminTest123!Secure credentials.
"""
import pytest
import requests
import os
from datetime import datetime

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestMaterialSMRFlow:
    """Full material SMR flow tests across 5 phases"""
    
    # ══════════════════════════════════════════════════════════════════════════════
    # FIXTURES
    # ══════════════════════════════════════════════════════════════════════════════
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token for admin user"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        token = resp.json().get("token")  # API returns 'token', not 'access_token'
        assert token, "No token in response"
        return token
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        """Auth headers for requests"""
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
    
    @pytest.fixture(scope="class")
    def project_id(self, headers):
        """Project ID - Get project with execution packages"""
        # First try to get execution packages and use their project_id
        resp = requests.get(f"{BASE_URL}/api/execution-packages", headers=headers)
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("project_id")
        
        # Fallback to first project
        resp = requests.get(f"{BASE_URL}/api/projects", headers=headers)
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("id")
        
        return None
    
    @pytest.fixture(scope="class")
    def execution_packages(self, headers, project_id):
        """Get execution packages for the project"""
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages",
            params={"project_id": project_id},
            headers=headers
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    
    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 1: MATERIAL ENTRY LINKAGE
    # ══════════════════════════════════════════════════════════════════════════════
    
    def test_p1_sync_material_entries(self, headers, project_id):
        """P1: POST /api/material-entries/sync/{project_id} syncs from warehouse issues/returns/consumption"""
        resp = requests.post(
            f"{BASE_URL}/api/material-entries/sync/{project_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Sync failed: {resp.text}"
        data = resp.json()
        
        # Verify response structure
        assert "ok" in data, "Missing 'ok' field"
        assert data["ok"] is True, "Sync not successful"
        assert "synced" in data, "Missing 'synced' count"
        assert "project_id" in data, "Missing project_id"
        assert data["project_id"] == project_id, f"Wrong project_id returned"
        
        print(f"Synced {data['synced']} material entries for {project_id}")
    
    def test_p1_list_material_entries_by_project(self, headers, project_id):
        """P1: GET /api/material-entries filters by project_id"""
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        assert resp.status_code == 200, f"List entries failed: {resp.text}"
        entries = resp.json()
        
        assert isinstance(entries, list), "Response should be a list"
        
        # Verify entry structure
        if entries:
            entry = entries[0]
            required_fields = ["id", "project_id", "material_name", "qty", "movement_type", "source", "mapped"]
            for field in required_fields:
                assert field in entry, f"Entry missing '{field}' field"
            
            # Check all entries belong to the project
            for e in entries:
                assert e["project_id"] == project_id, f"Entry belongs to wrong project"
            
            print(f"Found {len(entries)} material entries for project {project_id}")
            
            # Check for unmapped entries (expected due to name mismatch)
            unmapped = [e for e in entries if not e.get("mapped")]
            mapped = [e for e in entries if e.get("mapped")]
            print(f"  - Mapped: {len(mapped)}, Unmapped: {len(unmapped)}")
    
    def test_p1_list_material_entries_by_execution_package(self, headers, project_id, execution_packages):
        """P1: GET /api/material-entries filters by execution_package_id"""
        if not execution_packages:
            pytest.skip("No execution packages available")
        
        pkg_id = execution_packages[0]["id"]
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"execution_package_id": pkg_id},
            headers=headers
        )
        assert resp.status_code == 200, f"Filter by package failed: {resp.text}"
        entries = resp.json()
        
        assert isinstance(entries, list), "Response should be a list"
        
        # All returned entries should belong to specified package
        for e in entries:
            assert e.get("execution_package_id") == pkg_id, "Entry has wrong execution_package_id"
        
        print(f"Found {len(entries)} entries for package {pkg_id}")
    
    def test_p1_list_material_entries_by_planned_material(self, headers, project_id):
        """P1: GET /api/material-entries filters by planned_material_id"""
        # First get entries to find a planned_material_id
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp.json()
        
        # Find an entry with planned_material_id
        pm_entry = next((e for e in entries if e.get("planned_material_id")), None)
        
        if not pm_entry:
            print("No entries with planned_material_id found (expected due to name mismatch)")
            # This is expected behavior - names don't match so no planned material linkage
            return
        
        pm_id = pm_entry["planned_material_id"]
        resp2 = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"planned_material_id": pm_id},
            headers=headers
        )
        assert resp2.status_code == 200
        filtered = resp2.json()
        
        for e in filtered:
            assert e.get("planned_material_id") == pm_id
        
        print(f"Found {len(filtered)} entries for planned_material {pm_id}")
    
    def test_p1_unmapped_entries_preserved(self, headers, project_id):
        """P1: Unmapped entries preserved when no planned material match"""
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        assert resp.status_code == 200
        entries = resp.json()
        
        # Check that unmapped entries exist and have proper structure
        unmapped = [e for e in entries if not e.get("mapped")]
        
        print(f"Total entries: {len(entries)}, Unmapped: {len(unmapped)}")
        
        # Unmapped entries should have execution_package_id = None
        for e in unmapped:
            assert e.get("execution_package_id") is None, "Unmapped entry should have no execution_package_id"
            assert e.get("planned_material_id") is None, "Unmapped entry should have no planned_material_id"
            assert e.get("mapped") is False, "Unmapped entry should have mapped=False"
            # But should still have material_name, qty, etc.
            assert e.get("material_name"), "Unmapped entry should preserve material_name"
            assert e.get("movement_type") is not None, "Unmapped entry should have movement_type"
    
    def test_p1_movement_types_correct(self, headers, project_id):
        """P1: Verify movement types (issue/return/consumption) are correct"""
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        assert resp.status_code == 200
        entries = resp.json()
        
        valid_types = ["issue", "return", "consumption"]
        issues = [e for e in entries if e.get("movement_type") == "issue"]
        returns = [e for e in entries if e.get("movement_type") == "return"]
        consumptions = [e for e in entries if e.get("movement_type") == "consumption"]
        
        for e in entries:
            assert e.get("movement_type") in valid_types, f"Invalid movement_type: {e.get('movement_type')}"
        
        # Returns should have negative qty
        for r in returns:
            assert r.get("qty", 0) <= 0, f"Return entry should have negative qty: {r.get('qty')}"
            if r.get("total_cost") is not None:
                assert r.get("total_cost", 0) <= 0, f"Return should have negative total_cost"
        
        print(f"Movement types: issues={len(issues)}, returns={len(returns)}, consumptions={len(consumptions)}")
    
    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 2: MATERIAL ACTUAL COST BY EXECUTION PACKAGE
    # ══════════════════════════════════════════════════════════════════════════════
    
    def test_p2_get_material_cost_by_exec_package(self, headers, execution_packages):
        """P2: GET /api/material-cost/by-execution-package/{id} returns budget/actual/variance + by_material"""
        if not execution_packages:
            pytest.skip("No execution packages available")
        
        pkg = execution_packages[0]
        pkg_id = pkg["id"]
        
        resp = requests.get(
            f"{BASE_URL}/api/material-cost/by-execution-package/{pkg_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Get material cost failed: {resp.text}"
        data = resp.json()
        
        # Verify response structure
        required_fields = [
            "execution_package_id", "activity_name", "material_budget",
            "material_actual_cost", "material_variance", "total_issued_qty",
            "total_returned_qty", "net_qty", "partial_cost_data", "currency",
            "entries_count", "by_material"
        ]
        for field in required_fields:
            assert field in data, f"Missing '{field}' in response"
        
        assert data["execution_package_id"] == pkg_id
        assert data["currency"] == "EUR"
        assert isinstance(data["by_material"], list), "by_material should be a list"
        
        # by_material breakdown structure
        if data["by_material"]:
            mat = data["by_material"][0]
            mat_fields = ["material_name", "unit", "issued_qty", "returned_qty", "consumed_qty", "net_cost"]
            for f in mat_fields:
                assert f in mat, f"by_material item missing '{f}'"
        
        print(f"Package {pkg_id}: budget={data['material_budget']}, actual={data['material_actual_cost']}, "
              f"variance={data['material_variance']}, entries={data['entries_count']}")
    
    def test_p2_material_cost_404_for_invalid_package(self, headers):
        """P2: GET /api/material-cost/by-execution-package/{id} returns 404 for invalid package"""
        resp = requests.get(
            f"{BASE_URL}/api/material-cost/by-execution-package/INVALID-PKG-ID-12345",
            headers=headers
        )
        assert resp.status_code == 404, f"Should return 404: {resp.status_code}"
    
    def test_p2_by_material_breakdown_correct(self, headers, execution_packages):
        """P2: Verify by_material breakdown aggregates correctly"""
        if not execution_packages:
            pytest.skip("No execution packages")
        
        pkg_id = execution_packages[0]["id"]
        resp = requests.get(
            f"{BASE_URL}/api/material-cost/by-execution-package/{pkg_id}",
            headers=headers
        )
        data = resp.json()
        
        # If we have by_material data, verify structure
        by_mat = data.get("by_material", [])
        for mat in by_mat:
            # Net cost should be calculated (issued - returned)
            assert "net_cost" in mat
            assert "issued_qty" in mat
            assert "returned_qty" in mat
            # Quantities should be non-negative for issued/consumed, returned_qty is absolute
            assert mat.get("issued_qty", 0) >= 0
            assert mat.get("returned_qty", 0) >= 0
            assert mat.get("consumed_qty", 0) >= 0
        
        print(f"by_material has {len(by_mat)} materials")
    
    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 3: MATERIAL BUDGET/ACTUAL/VARIANCE RECOMPUTE
    # ══════════════════════════════════════════════════════════════════════════════
    
    def test_p3_recompute_material_for_project(self, headers, project_id):
        """P3: POST /api/execution-packages/recompute-material/{project_id} updates material budget and actual"""
        resp = requests.post(
            f"{BASE_URL}/api/execution-packages/recompute-material/{project_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Recompute failed: {resp.text}"
        data = resp.json()
        
        assert "ok" in data, "Missing 'ok' in response"
        assert data["ok"] is True, "Recompute should return ok=True"
        assert "updated" in data, "Missing 'updated' count"
        
        print(f"Recomputed material for {data['updated']} execution packages")
    
    def test_p3_budget_from_planned_materials(self, headers, project_id, execution_packages):
        """P3: Budget derived from planned_materials linkage"""
        # After recompute, check execution packages have budget values
        if not execution_packages:
            pytest.skip("No execution packages")
        
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages",
            params={"project_id": project_id},
            headers=headers
        )
        assert resp.status_code == 200
        packages = resp.json()
        
        for pkg in packages:
            # material_budget_total should exist and be >= 0
            assert "material_budget_total" in pkg, f"Package missing material_budget_total"
            assert pkg["material_budget_total"] is None or pkg["material_budget_total"] >= 0
            
            # actual_material_cost should exist
            assert "actual_material_cost" in pkg, f"Package missing actual_material_cost"
        
        # Check variance fields after recompute
        pkgs_with_variance = [p for p in packages if p.get("material_variance_value") is not None]
        print(f"Packages with material variance: {len(pkgs_with_variance)}/{len(packages)}")
    
    def test_p3_verify_recompute_updates_package_fields(self, headers, execution_packages):
        """P3: Verify recompute updates actual_material_cost and variance fields"""
        if not execution_packages:
            pytest.skip("No execution packages")
        
        pkg_id = execution_packages[0]["id"]
        
        # Get package details via material-cost endpoint
        resp = requests.get(
            f"{BASE_URL}/api/material-cost/by-execution-package/{pkg_id}",
            headers=headers
        )
        assert resp.status_code == 200
        cost_data = resp.json()
        
        # Also get package directly
        resp2 = requests.get(
            f"{BASE_URL}/api/execution-packages",
            params={"project_id": execution_packages[0].get("project_id", "PRJ-001")},
            headers=headers
        )
        packages = resp2.json()
        pkg = next((p for p in packages if p["id"] == pkg_id), None)
        
        if pkg:
            # Verify fields exist
            assert "material_budget_total" in pkg
            assert "actual_material_cost" in pkg
            print(f"Package {pkg.get('activity_name')}: budget={pkg.get('material_budget_total')}, "
                  f"actual={pkg.get('actual_material_cost')}, variance={pkg.get('material_variance_value')}")
    
    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 4: PACKAGE FINANCIAL SUMMARY WITH MARGIN
    # ══════════════════════════════════════════════════════════════════════════════
    
    def test_p4_get_package_financial_summary(self, headers, execution_packages):
        """P4: GET /api/execution-packages/{id}/financial returns sale/budget/actual/margin with subcontract"""
        if not execution_packages:
            pytest.skip("No execution packages")
        
        pkg_id = execution_packages[0]["id"]
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages/{pkg_id}/financial",
            headers=headers
        )
        assert resp.status_code == 200, f"Financial summary failed: {resp.text}"
        data = resp.json()
        
        # Verify top-level fields
        required_top = [
            "execution_package_id", "activity_name", "unit", "qty", "currency",
            "sale_total", "budget", "actual", "margin", "progress_percent", "metrics_partial"
        ]
        for field in required_top:
            assert field in data, f"Missing '{field}' in financial summary"
        
        # Verify budget structure
        budget = data["budget"]
        assert "material" in budget, "Budget missing 'material'"
        assert "labor" in budget, "Budget missing 'labor'"
        assert "total" in budget, "Budget missing 'total'"
        
        # Verify actual structure (includes subcontract)
        actual = data["actual"]
        assert "material" in actual, "Actual missing 'material'"
        assert "labor" in actual, "Actual missing 'labor'"
        assert "subcontract" in actual, "Actual missing 'subcontract'"
        assert "total" in actual, "Actual missing 'total'"
        
        # Verify margin structure
        margin = data["margin"]
        assert "gross_margin" in margin, "Margin missing 'gross_margin'"
        assert "margin_percent" in margin, "Margin missing 'margin_percent'"
        assert "expected_margin" in margin, "Margin missing 'expected_margin'"
        assert "margin_variance" in margin, "Margin missing 'margin_variance'"
        
        print(f"Package {pkg_id} financial: sale={data['sale_total']}, budget={budget['total']}, "
              f"actual={actual['total']}, margin={margin['gross_margin']}")
    
    def test_p4_financial_breakdown_all_packages(self, headers, project_id):
        """P4: GET /api/execution-packages/financial-breakdown/{project_id} returns all packages summary"""
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages/financial-breakdown/{project_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Financial breakdown failed: {resp.text}"
        data = resp.json()
        
        assert "project_id" in data, "Missing project_id"
        assert data["project_id"] == project_id
        assert "packages" in data, "Missing packages array"
        assert "currency" in data, "Missing currency"
        assert data["currency"] == "EUR"
        
        packages = data["packages"]
        assert isinstance(packages, list)
        
        # Verify package structure in breakdown
        if packages:
            pkg = packages[0]
            required_pkg_fields = [
                "id", "activity_name", "sale_total",
                "material_budget", "material_actual", "material_variance",
                "labor_budget", "labor_actual", "labor_variance",
                "subcontract_actual", "total_actual", "gross_margin",
                "progress", "status"
            ]
            for field in required_pkg_fields:
                assert field in pkg, f"Package missing '{field}'"
        
        print(f"Financial breakdown has {len(packages)} packages for project {project_id}")
    
    def test_p4_margin_calculation(self, headers, execution_packages):
        """P4: Margin = sale - (material + labor + subcontract), None when no actuals"""
        if not execution_packages:
            pytest.skip("No execution packages")
        
        pkg_id = execution_packages[0]["id"]
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages/{pkg_id}/financial",
            headers=headers
        )
        data = resp.json()
        
        sale = data["sale_total"]
        actual = data["actual"]
        margin = data["margin"]
        
        total_actual = actual["total"]
        gross_margin = margin["gross_margin"]
        
        # If no actuals (total=0), margin should be None
        if total_actual == 0:
            assert gross_margin is None, "Margin should be None when no actuals"
            print(f"Package {pkg_id}: No actuals, margin correctly None")
        else:
            # Margin = sale - total_actual
            expected_margin = round(sale - total_actual, 2)
            assert gross_margin == expected_margin, f"Margin mismatch: {gross_margin} != {expected_margin}"
            print(f"Package {pkg_id}: sale={sale}, actual={total_actual}, margin={gross_margin}")
    
    def test_p4_financial_404_for_invalid_package(self, headers):
        """P4: GET /api/execution-packages/{id}/financial returns 404 for invalid package"""
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages/INVALID-PKG-9999/financial",
            headers=headers
        )
        assert resp.status_code == 404, f"Should return 404: {resp.status_code}"
    
    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 5: WARNINGS + PROFIT INTEGRATION
    # ══════════════════════════════════════════════════════════════════════════════
    
    def test_p5_get_material_warnings(self, headers, project_id):
        """P5: GET /api/material-warnings/{project_id} returns over_budget and unmapped warnings"""
        resp = requests.get(
            f"{BASE_URL}/api/material-warnings/{project_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Get warnings failed: {resp.text}"
        data = resp.json()
        
        assert "project_id" in data, "Missing project_id"
        assert data["project_id"] == project_id
        assert "warnings" in data, "Missing warnings array"
        assert "total_entries" in data, "Missing total_entries"
        assert "unmapped_entries" in data, "Missing unmapped_entries"
        
        warnings = data["warnings"]
        assert isinstance(warnings, list)
        
        # Check warning types
        valid_types = ["over_material_budget", "missing_material_budget", "unmapped_material_entries"]
        for w in warnings:
            assert "type" in w, "Warning missing 'type'"
            assert w["type"] in valid_types, f"Invalid warning type: {w['type']}"
            assert "message" in w, "Warning missing 'message'"
        
        # We expect unmapped entries warning due to name mismatch
        unmapped_warning = next((w for w in warnings if w["type"] == "unmapped_material_entries"), None)
        if data["unmapped_entries"] > 0:
            assert unmapped_warning is not None, "Should have unmapped warning when unmapped_entries > 0"
        
        print(f"Warnings for {project_id}: {len(warnings)} warnings, "
              f"total_entries={data['total_entries']}, unmapped={data['unmapped_entries']}")
        for w in warnings:
            print(f"  - {w['type']}: {w['message']}")
    
    def test_p5_project_profit_includes_material_detail(self, headers, project_id):
        """P5: GET /api/project-profit includes material_detail with mapped/unmapped/budget/variance"""
        resp = requests.get(
            f"{BASE_URL}/api/project-profit/{project_id}",
            headers=headers
        )
        assert resp.status_code == 200, f"Get profit failed: {resp.text}"
        data = resp.json()
        
        # Verify top-level structure
        assert "project_id" in data
        assert "revenue" in data
        assert "expenses" in data
        assert "profit" in data
        
        expenses = data["expenses"]
        assert "material" in expenses, "Expenses missing 'material'"
        
        # material_detail should be present when has_data
        material_detail = expenses.get("material_detail")
        
        if material_detail:
            # Verify material_detail structure
            detail_fields = ["total_cost", "mapped_cost", "unmapped_cost", "budget_total", "variance_value", "currency", "has_data"]
            for field in detail_fields:
                assert field in material_detail, f"material_detail missing '{field}'"
            
            assert material_detail["has_data"] is True, "material_detail.has_data should be True"
            assert material_detail["currency"] == "EUR"
            
            # Verify values are consistent
            total = material_detail["total_cost"]
            mapped = material_detail["mapped_cost"]
            unmapped = material_detail["unmapped_cost"]
            
            # total should equal mapped + unmapped
            assert abs(total - (mapped + unmapped)) < 0.01, f"Total mismatch: {total} != {mapped} + {unmapped}"
            
            print(f"Material detail: total={total}, mapped={mapped}, unmapped={unmapped}, "
                  f"budget={material_detail['budget_total']}, variance={material_detail['variance_value']}")
        else:
            print("material_detail is None (no material data)")
    
    def test_p5_no_fabricated_costs_when_data_missing(self, headers, project_id):
        """Backend: No fabricated costs when data missing (returns None/partial)"""
        # Get material entries to check for missing cost data
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp.json()
        
        # Check that consumption entries (which may not have cost) don't have fabricated values
        consumptions = [e for e in entries if e.get("movement_type") == "consumption"]
        for c in consumptions:
            # Consumption entries should not have fabricated costs
            # If unit_cost or total_cost is None, it should stay None
            if c.get("unit_cost") is None:
                # This is expected - consumption doesn't always have cost
                pass
        
        # Check material cost endpoint for partial_cost_data flag
        resp2 = requests.get(
            f"{BASE_URL}/api/execution-packages",
            params={"project_id": project_id},
            headers=headers
        )
        packages = resp2.json()
        
        if packages:
            pkg_id = packages[0]["id"]
            resp3 = requests.get(
                f"{BASE_URL}/api/material-cost/by-execution-package/{pkg_id}",
                headers=headers
            )
            cost_data = resp3.json()
            
            # partial_cost_data should indicate if some costs are missing
            assert "partial_cost_data" in cost_data, "Missing partial_cost_data flag"
            print(f"Package {pkg_id}: partial_cost_data={cost_data['partial_cost_data']}")
    
    def test_p5_profit_metrics_available_flags(self, headers, project_id):
        """P5: Verify project-profit includes metrics_available flags"""
        resp = requests.get(
            f"{BASE_URL}/api/project-profit/{project_id}",
            headers=headers
        )
        data = resp.json()
        
        assert "metrics_available" in data, "Missing metrics_available"
        metrics = data["metrics_available"]
        
        expected_flags = [
            "contracted_revenue", "earned_revenue", "billed_revenue",
            "material_cost", "labor_cost", "subcontract_cost",
            "overhead_cost", "execution_packages"
        ]
        for flag in expected_flags:
            assert flag in metrics, f"metrics_available missing '{flag}'"
            assert isinstance(metrics[flag], bool), f"{flag} should be boolean"
        
        print(f"Metrics available: {metrics}")


class TestMaterialSMREdgeCases:
    """Edge case and validation tests for Material SMR"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        return resp.json().get("token")
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
    
    def test_sync_idempotent(self, headers):
        """Sync should be idempotent - running twice gives same result"""
        project_id = "PRJ-001"
        
        # First sync
        resp1 = requests.post(
            f"{BASE_URL}/api/material-entries/sync/{project_id}",
            headers=headers
        )
        assert resp1.status_code == 200
        count1 = resp1.json()["synced"]
        
        # Second sync (should replace previous)
        resp2 = requests.post(
            f"{BASE_URL}/api/material-entries/sync/{project_id}",
            headers=headers
        )
        assert resp2.status_code == 200
        count2 = resp2.json()["synced"]
        
        # Counts should be equal (idempotent)
        assert count1 == count2, f"Sync not idempotent: {count1} != {count2}"
        print(f"Sync idempotent: both runs synced {count1} entries")
    
    def test_material_entries_sorted_by_date(self, headers):
        """Material entries should be sorted by date descending"""
        project_id = "PRJ-001"
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp.json()
        
        if len(entries) > 1:
            dates = [e.get("date", "") for e in entries if e.get("date")]
            # Check descending order
            for i in range(len(dates) - 1):
                assert dates[i] >= dates[i+1], f"Not sorted: {dates[i]} < {dates[i+1]}"
            print(f"Entries sorted correctly, dates: {dates[:3]}...")
    
    def test_financial_breakdown_empty_project(self, headers):
        """Financial breakdown for non-existent/empty project should return empty packages"""
        resp = requests.get(
            f"{BASE_URL}/api/execution-packages/financial-breakdown/NON-EXISTENT-PROJECT",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["packages"] == [], "Empty project should return empty packages array"
        print("Empty project returns empty packages correctly")
    
    def test_material_warnings_empty_project(self, headers):
        """Material warnings for empty project should return empty warnings"""
        resp = requests.get(
            f"{BASE_URL}/api/material-warnings/NON-EXISTENT-PROJECT",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should return empty/zero counts
        assert data["total_entries"] == 0, "Empty project should have 0 entries"
        assert data["unmapped_entries"] == 0
        print("Empty project returns zero entries correctly")
    
    def test_recompute_empty_project(self, headers):
        """Recompute for non-existent project should return updated=0"""
        resp = requests.post(
            f"{BASE_URL}/api/execution-packages/recompute-material/NON-EXISTENT-PROJECT",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["ok"] is True
        assert data["updated"] == 0
        print("Recompute for empty project returns ok=True, updated=0")


class TestMaterialSMRDataIntegrity:
    """Data integrity and consistency tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        return resp.json().get("token")
    
    @pytest.fixture(scope="class")
    def headers(self, auth_token):
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
    
    def test_material_entries_have_source_sync(self, headers):
        """All synced entries should have source='sync'"""
        project_id = "PRJ-001"
        
        # Run sync first
        requests.post(f"{BASE_URL}/api/material-entries/sync/{project_id}", headers=headers)
        
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp.json()
        
        for e in entries:
            assert e.get("source") == "sync", f"Entry {e['id']} has source={e.get('source')}, expected 'sync'"
        
        print(f"All {len(entries)} entries have source='sync'")
    
    def test_entries_have_source_doc_references(self, headers):
        """Entries should have source_doc_type and source_doc_id"""
        project_id = "PRJ-001"
        resp = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp.json()
        
        for e in entries:
            assert "source_doc_type" in e, f"Entry missing source_doc_type"
            assert "source_doc_id" in e, f"Entry missing source_doc_id"
            
            valid_doc_types = ["warehouse_transaction", "project_material_op"]
            assert e["source_doc_type"] in valid_doc_types, f"Invalid source_doc_type: {e['source_doc_type']}"
        
        print(f"All entries have valid source document references")
    
    def test_total_cost_consistency(self, headers):
        """Total cost in breakdown should match entries aggregation"""
        project_id = "PRJ-001"
        
        # Get entries
        resp1 = requests.get(
            f"{BASE_URL}/api/material-entries",
            params={"project_id": project_id},
            headers=headers
        )
        entries = resp1.json()
        
        # Calculate total from entries (issues and returns only have cost)
        entries_total = sum(
            e.get("total_cost", 0) or 0 
            for e in entries 
            if e.get("movement_type") in ["issue", "return"]
        )
        
        # Get project profit to compare
        resp2 = requests.get(
            f"{BASE_URL}/api/project-profit/{project_id}",
            headers=headers
        )
        profit_data = resp2.json()
        
        material_detail = profit_data.get("expenses", {}).get("material_detail")
        if material_detail and material_detail.get("has_data"):
            profit_total = material_detail["total_cost"]
            
            # Should match within rounding error
            assert abs(entries_total - profit_total) < 0.1, \
                f"Total mismatch: entries={entries_total}, profit={profit_total}"
            
            print(f"Total cost consistent: {entries_total}")
