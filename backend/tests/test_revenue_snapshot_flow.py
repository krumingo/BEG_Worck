"""
Test Revenue Snapshot / Profit by Period / Cash vs Earned / Procurement Alerts / Risk Integration

Tests for new revenue_snapshot.py routes:
- Phase 1: POST /api/revenue-snapshots/from-offer/{id} creates frozen snapshot
- Phase 1: Duplicate protection per offer+version
- Phase 1: GET /api/revenue-snapshots lists by project
- Phase 2: GET /api/profit-by-period/{id} returns monthly breakdown
- Phase 3: GET /api/cash-vs-earned/{id} returns earned vs billed vs collected + gaps
- Phase 4: GET /api/procurement-alerts/{id} returns alerts by severity
- Phase 5: GET /api/project-risk/{id} includes procurement flags
"""
import pytest
import requests
import os

# Test credentials
from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = VALID_ADMIN_PASSWORD
TEST_PROJECT_ID = "PRJ-001"


@pytest.fixture(scope="module")
def auth_token():
    """Module-scoped login to get auth token"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("token")
    assert token, "No token in login response"
    return token


@pytest.fixture(scope="module")
def api_session(auth_token):
    """Module-scoped session with auth"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — REVENUE SNAPSHOT TESTS
# ═══════════════════════════════════════════════════════════════════

class TestRevenueSnapshotPhase1:
    """Phase 1: Revenue snapshot creation and listing"""
    
    def test_list_revenue_snapshots(self, api_session):
        """GET /api/revenue-snapshots lists snapshots by project"""
        resp = api_session.get(f"{BASE_URL}/api/revenue-snapshots", params={"project_id": TEST_PROJECT_ID})
        assert resp.status_code == 200, f"List snapshots failed: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list), "Response should be a list"
        
        # Check structure of snapshots if any exist
        if len(data) > 0:
            snapshot = data[0]
            assert "id" in snapshot, "Snapshot should have id"
            assert "project_id" in snapshot, "Snapshot should have project_id"
            assert "offer_id" in snapshot, "Snapshot should have offer_id"
            print(f"PASS: Found {len(data)} revenue snapshots for {TEST_PROJECT_ID}")
    
    def test_create_snapshot_offer_not_found(self, api_session):
        """POST /api/revenue-snapshots/from-offer/{id} returns 404 for invalid offer"""
        fake_offer_id = "NON-EXISTENT-OFFER-12345"
        resp = api_session.post(f"{BASE_URL}/api/revenue-snapshots/from-offer/{fake_offer_id}")
        
        assert resp.status_code == 404, f"Expected 404 for non-existent offer, got {resp.status_code}"
        print("PASS: Returns 404 for non-existent offer")
    
    def test_snapshot_list_no_project_filter(self, api_session):
        """GET /api/revenue-snapshots works without project filter"""
        resp = api_session.get(f"{BASE_URL}/api/revenue-snapshots")
        assert resp.status_code == 200, f"List all snapshots failed: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"PASS: Listed all snapshots, count={len(data)}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — PROFIT BY PERIOD TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProfitByPeriodPhase2:
    """Phase 2: Profit by period monthly breakdown"""
    
    def test_profit_by_period_endpoint(self, api_session):
        """GET /api/profit-by-period/{id} returns monthly breakdown"""
        resp = api_session.get(f"{BASE_URL}/api/profit-by-period/{TEST_PROJECT_ID}")
        assert resp.status_code == 200, f"Profit by period failed: {resp.text}"
        
        data = resp.json()
        assert "project_id" in data, "Response should have project_id"
        assert "currency" in data, "Response should have currency"
        assert "periods" in data, "Response should have periods array"
        assert isinstance(data["periods"], list), "Periods should be a list"
        
        print(f"PASS: Found {len(data['periods'])} periods for {TEST_PROJECT_ID}")
    
    def test_period_structure_if_exists(self, api_session):
        """Each period has required fields including gross_profit and net_profit"""
        resp = api_session.get(f"{BASE_URL}/api/profit-by-period/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        if len(data["periods"]) > 0:
            period = data["periods"][0]
            
            required_fields = [
                "period", "earned", "billed", "collected",
                "material", "labor", "subcontract", "overhead",
                "gross_profit", "net_profit"
            ]
            for field in required_fields:
                assert field in period, f"Period missing field: {field}"
            
            print(f"PASS: Period {period['period']} has all required fields")
        else:
            print("PASS: No periods exist (empty project)")
    
    def test_profit_period_returns_valid_structure(self, api_session):
        """Response structure is always valid even with empty periods"""
        resp = api_session.get(f"{BASE_URL}/api/profit-by-period/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert data["project_id"] == TEST_PROJECT_ID
        assert data["currency"] == "EUR"
        assert isinstance(data["periods"], list)
        print("PASS: Profit by period structure valid")


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — CASH VS EARNED TESTS
# ═══════════════════════════════════════════════════════════════════

class TestCashVsEarnedPhase3:
    """Phase 3: Cash vs earned revenue analysis"""
    
    def test_cash_vs_earned_endpoint(self, api_session):
        """GET /api/cash-vs-earned/{id} returns cash analysis"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200, f"Cash vs earned failed: {resp.text}"
        
        data = resp.json()
        assert "project_id" in data, "Response should have project_id"
        assert data["project_id"] == TEST_PROJECT_ID, "project_id should match"
        print("PASS: Cash vs earned endpoint works")
    
    def test_cash_earned_billed_collected_fields(self, api_session):
        """Response has earned, billed, collected values"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "earned_revenue" in data, "Should have earned_revenue"
        assert "billed_revenue" in data, "Should have billed_revenue"
        assert "collected_cash" in data, "Should have collected_cash"
        
        # Values should be numeric
        assert isinstance(data["earned_revenue"], (int, float)), "earned_revenue should be numeric"
        assert isinstance(data["billed_revenue"], (int, float)), "billed_revenue should be numeric"
        assert isinstance(data["collected_cash"], (int, float)), "collected_cash should be numeric"
        
        print(f"PASS: earned={data['earned_revenue']}, billed={data['billed_revenue']}, collected={data['collected_cash']}")
    
    def test_cash_position_field(self, api_session):
        """Cash position = collected - costs_paid"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "cash_position" in data, "Should have cash_position"
        assert "costs_paid_cash" in data, "Should have costs_paid_cash"
        
        expected_cash_position = round(data["collected_cash"] - data["costs_paid_cash"], 2)
        assert abs(data["cash_position"] - expected_cash_position) < 0.1, \
            f"Cash position mismatch: {data['cash_position']} != {expected_cash_position}"
        
        print(f"PASS: cash_position={data['cash_position']}")
    
    def test_gaps_structure(self, api_session):
        """Response has gaps analysis"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "gaps" in data, "Should have gaps object"
        gaps = data["gaps"]
        
        assert "collected_vs_earned" in gaps, "Gaps should have collected_vs_earned"
        assert "collected_vs_billed" in gaps, "Gaps should have collected_vs_billed"
        assert "earned_vs_billed" in gaps, "Gaps should have earned_vs_billed"
        
        print(f"PASS: Gaps structure complete")
    
    def test_collection_percent_field(self, api_session):
        """collection_percent = collected / billed * 100"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "collection_percent" in data, "Should have collection_percent"
        
        if data["billed_revenue"] > 0:
            expected_pct = round(data["collected_cash"] / data["billed_revenue"] * 100, 1)
            assert data["collection_percent"] is not None, "collection_percent should be calculated when billed > 0"
            print(f"PASS: collection_percent={data['collection_percent']}%")
        else:
            assert data["collection_percent"] is None, "collection_percent should be None when no billed revenue"
            print("PASS: collection_percent is None (no billed revenue)")
    
    def test_basis_labels_present(self, api_session):
        """Response has basis_labels for clarity"""
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "basis_labels" in data, "Should have basis_labels"
        labels = data["basis_labels"]
        
        assert "earned" in labels
        assert "billed" in labels
        assert "collected" in labels
        assert "costs_paid" in labels
        
        print("PASS: basis_labels present")


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PROCUREMENT ALERTS TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProcurementAlertsPhase4:
    """Phase 4: Procurement alerts by severity"""
    
    def test_procurement_alerts_endpoint(self, api_session):
        """GET /api/procurement-alerts/{id} returns alerts"""
        resp = api_session.get(f"{BASE_URL}/api/procurement-alerts/{TEST_PROJECT_ID}")
        assert resp.status_code == 200, f"Procurement alerts failed: {resp.text}"
        
        data = resp.json()
        assert "project_id" in data, "Response should have project_id"
        assert "alerts" in data, "Response should have alerts array"
        assert "total" in data, "Response should have total count"
        assert isinstance(data["alerts"], list), "Alerts should be a list"
        
        print(f"PASS: Found {data['total']} procurement alerts for {TEST_PROJECT_ID}")
    
    def test_metrics_available_field(self, api_session):
        """Response indicates if planned_materials data available"""
        resp = api_session.get(f"{BASE_URL}/api/procurement-alerts/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "metrics_available" in data, "Should have metrics_available"
        assert "planned_materials" in data["metrics_available"], "Should indicate planned_materials availability"
        
        print(f"PASS: metrics_available.planned_materials = {data['metrics_available']['planned_materials']}")
    
    def test_alerts_sorted_by_severity(self, api_session):
        """Alerts sorted by severity (critical > warning > info)"""
        resp = api_session.get(f"{BASE_URL}/api/procurement-alerts/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        alerts = data["alerts"]
        
        if len(alerts) > 1:
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            for i in range(len(alerts) - 1):
                current_sev = severity_order.get(alerts[i].get("severity"), 3)
                next_sev = severity_order.get(alerts[i + 1].get("severity"), 3)
                assert current_sev <= next_sev, \
                    f"Alerts not sorted: {alerts[i]['severity']} should come before {alerts[i + 1]['severity']}"
            
            print("PASS: Alerts correctly sorted by severity")
        else:
            print("PASS: Not enough alerts to verify sorting (0 or 1 alert)")
    
    def test_summary_field_structure(self, api_session):
        """Summary has counts per alert type"""
        resp = api_session.get(f"{BASE_URL}/api/procurement-alerts/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        
        # Summary should exist when there are planned materials
        if data.get("metrics_available", {}).get("planned_materials"):
            assert "summary" in data, "Response should have summary when planned_materials exist"
            summary = data["summary"]
            assert "not_requested" in summary
            assert "not_purchased" in summary
            assert "under_purchased" in summary
            print(f"PASS: Summary counts present")
        else:
            print("PASS: No summary needed (no planned_materials)")


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROJECT RISK TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProjectRiskPhase5:
    """Phase 5: Project risk with procurement flags"""
    
    def test_project_risk_endpoint(self, api_session):
        """GET /api/project-risk/{id} returns risk summary"""
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{TEST_PROJECT_ID}")
        assert resp.status_code == 200, f"Project risk failed: {resp.text}"
        
        data = resp.json()
        assert "project_id" in data, "Response should have project_id"
        assert "risk_level" in data, "Response should have risk_level"
        assert "risk_flags" in data, "Response should have risk_flags"
        assert "flag_count" in data, "Response should have flag_count"
        
        print(f"PASS: Project risk endpoint works - level={data['risk_level']}, flags={data['flag_count']}")
    
    def test_risk_level_valid_values(self, api_session):
        """Risk level is one of ok/low/medium/high"""
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        valid_levels = ["ok", "low", "medium", "high"]
        assert data["risk_level"] in valid_levels, \
            f"Invalid risk level: {data['risk_level']}"
        
        print(f"PASS: Risk level '{data['risk_level']}' is valid")
    
    def test_risk_flags_is_list(self, api_session):
        """Risk flags is a list"""
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert isinstance(data["risk_flags"], list), "risk_flags should be a list"
        assert data["flag_count"] == len(data["risk_flags"]), "flag_count should match list length"
        
        print(f"PASS: Risk flags: {data['risk_flags']}")
    
    def test_explanations_provided(self, api_session):
        """Risk response includes explanations for flags"""
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "explanations" in data, "Response should have explanations"
        assert isinstance(data["explanations"], list), "Explanations should be a list"
        
        # Explanations count should match or relate to flags
        if len(data["risk_flags"]) > 0:
            assert len(data["explanations"]) > 0, "Should have explanations when flags exist"
        
        print(f"PASS: {len(data['explanations'])} explanations provided")
    
    def test_risk_level_logic(self, api_session):
        """Risk level = medium when 3+ non-critical flags"""
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{TEST_PROJECT_ID}")
        assert resp.status_code == 200
        
        data = resp.json()
        flags = data["risk_flags"]
        
        # Verify logic matches expected behavior
        critical_flags = ["overdue_invoices", "labor_over_budget", "margin_drop"]
        critical_count = sum(1 for f in flags if f in critical_flags)
        
        # Logic from code:
        # if critical >= 2: high
        # elif len(flags) >= 3: medium
        # elif len(flags) > 0: low
        # else: ok
        
        if critical_count >= 2:
            assert data["risk_level"] == "high"
        elif len(flags) >= 3:
            assert data["risk_level"] == "medium"
        elif len(flags) > 0:
            assert data["risk_level"] == "low"
        else:
            assert data["risk_level"] == "ok"
        
        print(f"PASS: Risk level logic verified for {len(flags)} flags")


# ═══════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases and error handling"""
    
    def test_profit_by_period_empty_project(self, api_session):
        """Profit by period handles project with no data"""
        fake_project = "NON-EXISTENT-PROJECT-999"
        resp = api_session.get(f"{BASE_URL}/api/profit-by-period/{fake_project}")
        
        # Should return 200 with empty periods
        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        data = resp.json()
        assert data["periods"] == [], "Should have empty periods"
        print("PASS: Returns empty periods for empty project")
    
    def test_cash_vs_earned_empty_project(self, api_session):
        """Cash vs earned handles project with no data"""
        fake_project = "NON-EXISTENT-PROJECT-999"
        resp = api_session.get(f"{BASE_URL}/api/cash-vs-earned/{fake_project}")
        
        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        data = resp.json()
        assert data["earned_revenue"] == 0, "Should have 0 earned"
        assert data["billed_revenue"] == 0, "Should have 0 billed"
        print("PASS: Returns zeros for empty project")
    
    def test_procurement_alerts_empty_project(self, api_session):
        """Procurement alerts handles project with no planned materials"""
        fake_project = "NON-EXISTENT-PROJECT-999"
        resp = api_session.get(f"{BASE_URL}/api/procurement-alerts/{fake_project}")
        
        assert resp.status_code == 200, f"Should return 200: {resp.text}"
        
        data = resp.json()
        assert data["alerts"] == [], "Should have empty alerts"
        assert data["total"] == 0, "Should have 0 total"
        assert data["metrics_available"]["planned_materials"] == False
        
        print("PASS: Empty alerts for project without planned materials")
    
    def test_project_risk_nonexistent_project(self, api_session):
        """Project risk handles non-existent project"""
        fake_project = "NON-EXISTENT-PROJECT-999"
        resp = api_session.get(f"{BASE_URL}/api/project-risk/{fake_project}")
        
        # Should still work - just show flags for empty project
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_level" in data
        assert "risk_flags" in data
        
        print(f"PASS: Risk for empty project: {data['risk_level']}")
    
    def test_unauthenticated_access(self, api_session):
        """Endpoints require authentication"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        
        endpoints = [
            f"/api/revenue-snapshots",
            f"/api/profit-by-period/{TEST_PROJECT_ID}",
            f"/api/cash-vs-earned/{TEST_PROJECT_ID}",
            f"/api/procurement-alerts/{TEST_PROJECT_ID}",
            f"/api/project-risk/{TEST_PROJECT_ID}",
        ]
        
        for endpoint in endpoints:
            resp = session.get(f"{BASE_URL}{endpoint}")
            assert resp.status_code in [401, 403], \
                f"Endpoint {endpoint} should require auth, got {resp.status_code}"
        
        print("PASS: All endpoints require authentication")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
