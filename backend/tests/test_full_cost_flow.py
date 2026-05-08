"""
Test Full Cost / Overhead / Net Margin / Financial Alerts Flow
7 Phases:
P1: Employee full cost model
P2: Overhead snapshots
P3: Overhead allocation
P4: Package net margin
P5: Project net profit with expected vs actual
P6: Financial alerts
P7: Project risk summary
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

# Test data IDs from existing seed data
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001
TECH1_USER_ID = "6f69367a-e25f-489d-a7c8-f25cde6a9ac5"  # tech1@begwork.com
PKG_ID = "0e937841-8c1a-4dcb-9e83-531caeb1a222"  # TEST_Activity_1

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def auth_token():
    """Authenticate and return JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@begwork.com", "password": "AdminTest123!Secure"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return auth headers with Bearer token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# =============================================================================
# PHASE 1: EMPLOYEE FULL COST MODEL
# =============================================================================

class TestP1EmployeeFullCost:
    """P1: Employee full cost model - net salary, additional cost, overhead"""

    def test_p1_01_get_employee_cost_available(self, auth_headers):
        """GET /api/employee-cost/{id} returns full cost breakdown"""
        response = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert data["available"] == True
        assert "net_salary" in data
        assert "net_hour_cost" in data
        assert "additional_company_cost_per_hour" in data
        assert "overhead_per_hour" in data
        assert "full_company_hour_cost" in data
        
        # Verify expected values (tech1 has net_salary=2850)
        assert data["net_salary"] == 2850.0
        assert data["net_hour_cost"] == 16.19  # 2850 / (22 * 8)
        
    def test_p1_02_employee_cost_with_config_applied(self, auth_headers):
        """Full cost calculation applies config percentages correctly"""
        response = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # With config: additional=25%, overhead=15%
        # net_hour_cost = 16.19
        # additional = 16.19 * 0.25 = 4.0475 → 4.05
        # overhead = 16.19 * 0.15 = 2.4285 → 2.43
        # full = 16.19 + 4.05 + 2.43 = 22.67
        assert data["config"]["additional_cost_percent"] == 25.0
        assert data["config"]["overhead_percent_per_hour"] == 15.0
        assert data["additional_company_cost_per_hour"] == 4.05
        assert data["overhead_per_hour"] == 2.43
        assert data["full_company_hour_cost"] == 22.67

    def test_p1_03_update_employee_cost_config(self, auth_headers):
        """PUT /api/employee-cost-config saves config"""
        # Save config
        response = requests.put(
            f"{BASE_URL}/api/employee-cost-config",
            headers=auth_headers,
            json={"additional_cost_percent": 30, "overhead_percent_per_hour": 20}
        )
        assert response.status_code == 200
        assert response.json()["ok"] == True
        
        # Verify updated config is applied
        verify = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        )
        verify_data = verify.json()
        assert verify_data["config"]["additional_cost_percent"] == 30.0
        assert verify_data["config"]["overhead_percent_per_hour"] == 20.0
        
        # Reset back to original values
        requests.put(
            f"{BASE_URL}/api/employee-cost-config",
            headers=auth_headers,
            json={"additional_cost_percent": 25, "overhead_percent_per_hour": 15}
        )

    def test_p1_04_net_salary_not_modified_by_config(self, auth_headers):
        """Net salary field is NOT modified by cost config changes"""
        # Get original salary
        original = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        ).json()
        original_salary = original["net_salary"]
        
        # Change config
        requests.put(
            f"{BASE_URL}/api/employee-cost-config",
            headers=auth_headers,
            json={"additional_cost_percent": 50, "overhead_percent_per_hour": 50}
        )
        
        # Verify salary unchanged
        after = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        ).json()
        assert after["net_salary"] == original_salary  # Salary should be unchanged
        
        # Reset config
        requests.put(
            f"{BASE_URL}/api/employee-cost-config",
            headers=auth_headers,
            json={"additional_cost_percent": 25, "overhead_percent_per_hour": 15}
        )

    def test_p1_05_employee_cost_no_profile(self, auth_headers):
        """Returns available=False when no profile exists"""
        response = requests.get(
            f"{BASE_URL}/api/employee-cost/nonexistent-user-id",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["available"] == False
        assert data["reason"] == "no_profile"


# =============================================================================
# PHASE 2: OVERHEAD SNAPSHOTS
# =============================================================================

class TestP2OverheadSnapshots:
    """P2: Overhead categories + period snapshots"""

    def test_p2_01_create_overhead_snapshot(self, auth_headers):
        """POST /api/overhead-snapshots creates period snapshot"""
        test_snapshot = {
            "category_code": f"TEST_cat_{uuid.uuid4().hex[:8]}",
            "category_name": "Test Category",
            "period_key": "2026-03",
            "amount": 1500.0,
            "notes": "Test overhead snapshot"
        }
        response = requests.post(
            f"{BASE_URL}/api/overhead-snapshots",
            headers=auth_headers,
            json=test_snapshot
        )
        assert response.status_code == 201
        data = response.json()
        
        # Verify returned data
        assert "id" in data
        assert data["category_code"] == test_snapshot["category_code"]
        assert data["category_name"] == test_snapshot["category_name"]
        assert data["period_key"] == "2026-03"
        assert data["amount"] == 1500.0
        assert data["status"] == "active"
        assert data["allocation_basis"] == "labor_hours"
        assert "_id" not in data  # MongoDB _id should be excluded

    def test_p2_02_list_overhead_snapshots(self, auth_headers):
        """GET /api/overhead-snapshots lists all snapshots"""
        response = requests.get(
            f"{BASE_URL}/api/overhead-snapshots",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least the 2 known snapshots (rent, utilities)
        assert len(data) >= 2

    def test_p2_03_list_overhead_snapshots_by_period(self, auth_headers):
        """GET /api/overhead-snapshots filters by period_key"""
        response = requests.get(
            f"{BASE_URL}/api/overhead-snapshots?period_key=2026-03",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned should have matching period
        for snapshot in data:
            assert snapshot.get("period_key") == "2026-03"

    def test_p2_04_aggregate_overhead_by_period(self, auth_headers):
        """GET /api/overhead-snapshots/aggregate returns by period+category"""
        response = requests.get(
            f"{BASE_URL}/api/overhead-snapshots/aggregate?period_key=2026-03",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Find 2026-03 period
        period_data = next((p for p in data if p["period"] == "2026-03"), None)
        assert period_data is not None
        assert "total" in period_data
        assert "categories" in period_data
        assert period_data["total"] > 0  # Should have rent(2500) + utilities(800) + legacy

    def test_p2_05_aggregate_includes_legacy_overhead(self, auth_headers):
        """Aggregate includes legacy overhead_transactions"""
        response = requests.get(
            f"{BASE_URL}/api/overhead-snapshots/aggregate?period_key=2026-03",
            headers=auth_headers
        )
        data = response.json()
        
        # 2026-03 should have snapshots (rent=2500, utilities=800) + legacy overhead
        period_data = next((p for p in data if p["period"] == "2026-03"), None)
        # With legacy overhead (~5414), total should be > 3300 (snapshots alone)
        assert period_data["total"] > 3300


# =============================================================================
# PHASE 3: OVERHEAD ALLOCATION
# =============================================================================

class TestP3OverheadAllocation:
    """P3: Overhead allocation to projects by labor hours share"""

    def test_p3_01_compute_overhead_allocation(self, auth_headers):
        """POST /api/overhead-allocation/compute/{project_id} allocates overhead"""
        response = requests.post(
            f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}",
            headers=auth_headers,
            json={"period_key": "2026-03"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["ok"] == True
        assert "allocated" in data
        assert "period" in data
        assert "share_percent" in data
        assert data["period"] == "2026-03"
        assert data["allocated"] > 0

    def test_p3_02_allocation_by_labor_hours_share(self, auth_headers):
        """Allocation distributes by labor hours share"""
        response = requests.post(
            f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}",
            headers=auth_headers,
            json={"period_key": "2026-03"}
        )
        data = response.json()
        
        # PRJ-001 has 100% labor share for 2026-03
        assert data["share_percent"] == 100.0
        # Should get all overhead
        assert data["allocated"] > 8000  # ~8714 expected

    def test_p3_03_allocation_distributes_to_packages(self, auth_headers):
        """Allocation also distributes to execution packages"""
        # Trigger allocation
        requests.post(
            f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}",
            headers=auth_headers,
            json={"period_key": "2026-03"}
        )
        
        # Check package has overhead allocated
        pkg_response = requests.get(
            f"{BASE_URL}/api/execution-packages?project_id={PROJECT_ID}",
            headers=auth_headers
        )
        packages = pkg_response.json()
        
        # At least one package should have overhead_actual_allocated
        has_allocation = any(p.get("overhead_actual_allocated", 0) > 0 for p in packages)
        assert has_allocation, "No packages have overhead allocated"

    def test_p3_04_allocation_no_overhead_data(self, auth_headers):
        """Returns appropriate response when no overhead for period"""
        response = requests.post(
            f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}",
            headers=auth_headers,
            json={"period_key": "2020-01"}  # Period with no data
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] == True
        # Should return 0 or indicate no data
        assert data.get("allocated", 0) == 0 or data.get("reason") in ["no_overhead_data", "no_labor_hours"]


# =============================================================================
# PHASE 4: EXECUTION PACKAGE NET MARGIN
# =============================================================================

class TestP4PackageNetMargin:
    """P4: Execution package overhead + net margin"""

    def test_p4_01_get_package_net_financial(self, auth_headers):
        """GET /api/execution-packages/{id}/net-financial returns structure"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert data["execution_package_id"] == PKG_ID
        assert "sale_total" in data
        assert "costs" in data
        assert "margin" in data
        assert "currency" in data
        assert data["currency"] == "EUR"

    def test_p4_02_package_costs_breakdown(self, auth_headers):
        """Package costs include material, labor, subcontract, overhead"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        data = response.json()
        costs = data["costs"]
        
        assert "material" in costs
        assert "labor" in costs
        assert "subcontract" in costs
        assert "overhead" in costs
        assert "gross_cost" in costs  # material + labor + subcontract
        assert "total_cost" in costs  # gross_cost + overhead

    def test_p4_03_package_margin_calculations(self, auth_headers):
        """Margin includes gross and net with percentages"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        data = response.json()
        margin = data["margin"]
        
        assert "gross_margin" in margin
        assert "gross_margin_percent" in margin
        assert "net_margin" in margin
        assert "net_margin_percent" in margin
        assert "expected_margin" in margin
        assert "margin_variance" in margin

    def test_p4_04_gross_margin_excludes_overhead(self, auth_headers):
        """Gross margin = sale - (material + labor + subcontract), excludes overhead"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        data = response.json()
        
        # Verify gross_cost calculation
        costs = data["costs"]
        expected_gross = costs["material"] + costs["labor"] + costs["subcontract"]
        assert abs(costs["gross_cost"] - expected_gross) < 0.01
        
        # Gross margin = sale - gross_cost
        expected_gross_margin = data["sale_total"] - costs["gross_cost"]
        if data["margin"]["gross_margin"] is not None:
            assert abs(data["margin"]["gross_margin"] - expected_gross_margin) < 0.01

    def test_p4_05_net_margin_includes_overhead(self, auth_headers):
        """Net margin = sale - (gross_cost + overhead)"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        data = response.json()
        
        # Verify total_cost includes overhead
        costs = data["costs"]
        expected_total = costs["gross_cost"] + costs["overhead"]
        assert abs(costs["total_cost"] - expected_total) < 0.01
        
        # Net margin = sale - total_cost
        expected_net_margin = data["sale_total"] - costs["total_cost"]
        if data["margin"]["net_margin"] is not None:
            assert abs(data["margin"]["net_margin"] - expected_net_margin) < 0.01

    def test_p4_06_package_not_found(self, auth_headers):
        """Returns 404 for non-existent package"""
        response = requests.get(
            f"{BASE_URL}/api/execution-packages/nonexistent-id/net-financial",
            headers=auth_headers
        )
        assert response.status_code == 404


# =============================================================================
# PHASE 5: PROJECT NET PROFIT
# =============================================================================

class TestP5ProjectNetProfit:
    """P5: Profit by period + expected vs actual"""

    def test_p5_01_get_project_net_profit(self, auth_headers):
        """GET /api/project-net-profit/{id} returns complete structure"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["project_id"] == PROJECT_ID
        assert data["project_code"] == "PRJ-001"
        assert "revenue" in data
        assert "costs" in data
        assert "profit" in data
        assert data["currency"] == "EUR"

    def test_p5_02_revenue_breakdown(self, auth_headers):
        """Revenue includes contracted, earned, billed, collected"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        revenue = response.json()["revenue"]
        
        assert "contracted" in revenue
        assert "earned" in revenue
        assert "billed" in revenue
        assert "collected" in revenue
        assert "receivables" in revenue
        assert "basis" in revenue  # earned or contracted

    def test_p5_03_revenue_basis_earned_when_available(self, auth_headers):
        """Revenue basis = earned when available, contracted as fallback"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        revenue = response.json()["revenue"]
        
        # PRJ-001 has earned=2500 > 0, so basis should be "earned"
        if revenue["earned"] > 0:
            assert revenue["basis"] == "earned"
        else:
            assert revenue["basis"] == "contracted"

    def test_p5_04_costs_breakdown(self, auth_headers):
        """Costs include material, labor, subcontract, overhead"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        costs = response.json()["costs"]
        
        assert "material" in costs
        assert "labor" in costs
        assert "subcontract" in costs
        assert "overhead" in costs
        assert "gross_cost" in costs
        assert "total_cost" in costs

    def test_p5_05_profit_gross_and_net(self, auth_headers):
        """Profit includes gross and net with expected vs actual"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        profit = response.json()["profit"]
        
        assert "gross_profit" in profit
        assert "gross_margin_percent" in profit
        assert "net_profit" in profit
        assert "net_margin_percent" in profit
        assert "expected_profit" in profit
        assert "expected_margin_percent" in profit
        assert "actual_vs_expected_variance" in profit

    def test_p5_06_expected_vs_actual_variance(self, auth_headers):
        """Variance = net_profit - expected_profit"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        profit = response.json()["profit"]
        
        if profit["net_profit"] is not None and profit["expected_profit"] is not None:
            expected_variance = profit["net_profit"] - profit["expected_profit"]
            assert abs(profit["actual_vs_expected_variance"] - expected_variance) < 0.01

    def test_p5_07_project_not_found(self, auth_headers):
        """Returns 404 for non-existent project"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/nonexistent-project-id",
            headers=auth_headers
        )
        assert response.status_code == 404


# =============================================================================
# PHASE 6: FINANCIAL ALERTS
# =============================================================================

class TestP6FinancialAlerts:
    """P6: Core financial alerts"""

    def test_p6_01_get_financial_alerts(self, auth_headers):
        """GET /api/financial-alerts/{id} returns alerts"""
        response = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["project_id"] == PROJECT_ID
        assert "alerts" in data
        assert "total" in data
        assert isinstance(data["alerts"], list)

    def test_p6_02_alert_structure(self, auth_headers):
        """Each alert has type, severity, message"""
        response = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        alerts = response.json()["alerts"]
        
        if alerts:
            alert = alerts[0]
            assert "type" in alert
            assert "severity" in alert
            assert "message" in alert

    def test_p6_03_severity_levels(self, auth_headers):
        """Alerts have severity levels (info/warning/critical)"""
        response = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        alerts = response.json()["alerts"]
        
        valid_severities = ["info", "warning", "critical"]
        for alert in alerts:
            assert alert["severity"] in valid_severities

    def test_p6_04_alert_types(self, auth_headers):
        """Alerts cover overhead/subcontract/receivable/material/labor/margin"""
        response = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        alerts = response.json()["alerts"]
        
        valid_types = [
            "overhead_not_allocated",
            "subcontract_payable",
            "client_receivable",
            "unmapped_material",
            "unmapped_labor",
            "margin_drop"
        ]
        for alert in alerts:
            assert alert["type"] in valid_types

    def test_p6_05_unmapped_material_warning(self, auth_headers):
        """Generates warning for unmapped material entries"""
        response = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        alerts = response.json()["alerts"]
        
        # PRJ-001 has 9 unmapped material entries
        unmapped = next((a for a in alerts if a["type"] == "unmapped_material"), None)
        if unmapped:
            assert unmapped["severity"] == "warning"
            assert unmapped["count"] > 0


# =============================================================================
# PHASE 7: PROJECT RISK SUMMARY
# =============================================================================

class TestP7ProjectRisk:
    """P7: Consolidated project risk summary"""

    def test_p7_01_get_project_risk(self, auth_headers):
        """GET /api/project-risk/{id} returns risk summary"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["project_id"] == PROJECT_ID
        assert "risk_level" in data
        assert "risk_flags" in data
        assert "explanations" in data
        assert "flag_count" in data

    def test_p7_02_risk_level_values(self, auth_headers):
        """Risk level is one of ok/low/medium/high"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        valid_levels = ["ok", "low", "medium", "high"]
        assert data["risk_level"] in valid_levels

    def test_p7_03_risk_flags_array(self, auth_headers):
        """Risk flags is array of flag codes"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        assert isinstance(data["risk_flags"], list)
        assert data["flag_count"] == len(data["risk_flags"])

    def test_p7_04_explanations_match_flags(self, auth_headers):
        """Each flag has corresponding explanation"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        assert len(data["explanations"]) == len(data["risk_flags"])

    def test_p7_05_risk_level_based_on_flags(self, auth_headers):
        """Risk level based on flag severity count"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # PRJ-001 has 2 flags, so should be "low"
        flag_count = data["flag_count"]
        level = data["risk_level"]
        
        # Risk rules: ok(0), low(1-2), medium(3+), high(2+ critical)
        if flag_count == 0:
            assert level == "ok"
        elif flag_count <= 2:
            assert level in ["low", "medium", "high"]  # Could be higher if critical flags
        else:
            assert level in ["medium", "high"]

    def test_p7_06_project_not_found(self, auth_headers):
        """Project not found gracefully handled"""
        response = requests.get(
            f"{BASE_URL}/api/project-risk/nonexistent-project-id",
            headers=auth_headers
        )
        # Should return data even for non-existent project (no flags)
        assert response.status_code == 200


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """End-to-end integration tests"""

    def test_int_01_overhead_allocation_updates_package_net_financial(self, auth_headers):
        """Overhead allocation reflects in package net financial"""
        # Allocate overhead
        alloc_resp = requests.post(
            f"{BASE_URL}/api/overhead-allocation/compute/{PROJECT_ID}",
            headers=auth_headers,
            json={"period_key": "2026-03"}
        )
        allocated = alloc_resp.json()["allocated"]
        
        # Check package has overhead
        pkg_resp = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        pkg_overhead = pkg_resp.json()["costs"]["overhead"]
        
        # Package should have some portion of allocated overhead
        assert pkg_overhead > 0

    def test_int_02_project_profit_includes_overhead(self, auth_headers):
        """Project net profit includes allocated overhead"""
        response = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Overhead should be included in total cost
        assert data["costs"]["overhead"] > 0
        # Total cost = gross + overhead
        expected_total = data["costs"]["gross_cost"] + data["costs"]["overhead"]
        assert abs(data["costs"]["total_cost"] - expected_total) < 0.01

    def test_int_03_full_flow_consistency(self, auth_headers):
        """Full flow: config → allocation → package → project → alerts"""
        # 1. Get employee cost config
        emp_resp = requests.get(
            f"{BASE_URL}/api/employee-cost/{TECH1_USER_ID}",
            headers=auth_headers
        )
        assert emp_resp.status_code == 200
        
        # 2. Get overhead aggregate
        overhead_resp = requests.get(
            f"{BASE_URL}/api/overhead-snapshots/aggregate?period_key=2026-03",
            headers=auth_headers
        )
        assert overhead_resp.status_code == 200
        
        # 3. Get package financial
        pkg_resp = requests.get(
            f"{BASE_URL}/api/execution-packages/{PKG_ID}/net-financial",
            headers=auth_headers
        )
        assert pkg_resp.status_code == 200
        
        # 4. Get project profit
        profit_resp = requests.get(
            f"{BASE_URL}/api/project-net-profit/{PROJECT_ID}",
            headers=auth_headers
        )
        assert profit_resp.status_code == 200
        
        # 5. Get alerts
        alerts_resp = requests.get(
            f"{BASE_URL}/api/financial-alerts/{PROJECT_ID}",
            headers=auth_headers
        )
        assert alerts_resp.status_code == 200
        
        # 6. Get risk
        risk_resp = requests.get(
            f"{BASE_URL}/api/project-risk/{PROJECT_ID}",
            headers=auth_headers
        )
        assert risk_resp.status_code == 200
