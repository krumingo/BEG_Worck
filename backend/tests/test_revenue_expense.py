"""
Tests for Revenue & Expense Core Backend (4 Phases)
Phase 1: Client Acts (earned revenue)
Phase 2: Labor Cost Aggregation
Phase 3: Execution Packages from offers
Phase 4: Project Profit Summary
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from main agent context
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Known project ID from context
PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"


class TestRevenueExpensePhase1ClientActs:
    """Phase 1: Client Acts (earned revenue) tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        self.token = data.get("access_token") or data.get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
    def test_create_draft_client_act_with_lines(self):
        """P1: POST /api/client-acts creates draft act with lines"""
        payload = {
            "project_id": PROJECT_ID,
            "act_date": "2026-01-15",
            "period_from": "2026-01-01",
            "period_to": "2026-01-15",
            "notes": "TEST_Revenue_Expense test act",
            "lines": [
                {
                    "activity_name": "TEST Wall Painting",
                    "unit": "m2",
                    "contracted_qty": 100,
                    "executed_qty": 50,
                    "unit_price": 15.0,
                    "note": "First floor"
                },
                {
                    "activity_name": "TEST Floor Tiling",
                    "unit": "m2",
                    "contracted_qty": 80,
                    "executed_qty": 40,
                    "unit_price": 25.0,
                    "note": "Kitchen area"
                }
            ]
        }
        response = requests.post(f"{BASE_URL}/api/client-acts", json=payload, headers=self.headers)
        assert response.status_code == 201, f"Failed to create client act: {response.text}"
        
        act = response.json()
        assert act["status"] == "Draft"
        assert act["project_id"] == PROJECT_ID
        assert len(act["lines"]) == 2
        
        # Verify line calculations
        line1 = act["lines"][0]
        assert line1["line_total"] == 750.0  # 50 * 15
        assert line1["executed_percent"] == 50.0  # 50/100 * 100
        
        line2 = act["lines"][1]
        assert line2["line_total"] == 1000.0  # 40 * 25
        
        # Verify totals
        expected_subtotal = 750.0 + 1000.0  # 1750
        assert act["subtotal"] == expected_subtotal
        assert act["vat_percent"] == 20
        assert act["vat_amount"] == round(expected_subtotal * 0.2, 2)  # 350
        assert act["total"] == round(expected_subtotal * 1.2, 2)  # 2100
        
        # Store act_id for later tests
        self.__class__.created_act_id = act["id"]
        print(f"✓ Created draft client act: {act['act_number']} (ID: {act['id']})")

    def test_get_client_acts_by_project(self):
        """P1: GET /api/client-acts?project_id returns acts for project"""
        response = requests.get(f"{BASE_URL}/api/client-acts", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert response.status_code == 200, f"Failed to list client acts: {response.text}"
        
        acts = response.json()
        assert isinstance(acts, list)
        assert len(acts) >= 1  # Should have at least one act
        
        # Verify all returned acts are for the correct project
        for act in acts:
            assert act["project_id"] == PROJECT_ID
            assert "id" in act
            assert "act_number" in act
            assert "status" in act
            assert "lines" in act
        print(f"✓ Found {len(acts)} client acts for project {PROJECT_ID}")

    def test_update_draft_act_lines_and_recalculate(self):
        """P1: PUT /api/client-acts/{id} updates draft act lines and recalculates totals"""
        # First get an existing draft act
        response = requests.get(f"{BASE_URL}/api/client-acts", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert response.status_code == 200
        acts = response.json()
        
        # Find a draft act
        draft_act = None
        for act in acts:
            if act["status"] == "Draft":
                draft_act = act
                break
        
        if not draft_act:
            pytest.skip("No draft act available to update")
        
        act_id = draft_act["id"]
        
        # Update with new lines
        update_payload = {
            "notes": "Updated TEST notes",
            "lines": [
                {
                    "id": draft_act["lines"][0]["id"] if draft_act["lines"] else None,
                    "activity_name": "TEST Updated Activity",
                    "unit": "m2",
                    "contracted_qty": 200,
                    "executed_qty": 100,
                    "unit_price": 20.0,
                    "note": "Updated line"
                }
            ]
        }
        
        response = requests.put(f"{BASE_URL}/api/client-acts/{act_id}", json=update_payload, headers=self.headers)
        assert response.status_code == 200, f"Failed to update client act: {response.text}"
        
        updated_act = response.json()
        assert updated_act["notes"] == "Updated TEST notes"
        assert len(updated_act["lines"]) == 1
        
        # Verify recalculation
        line = updated_act["lines"][0]
        assert line["line_total"] == 2000.0  # 100 * 20
        assert line["executed_percent"] == 50.0  # 100/200 * 100
        
        assert updated_act["subtotal"] == 2000.0
        assert updated_act["vat_amount"] == 400.0
        assert updated_act["total"] == 2400.0
        print(f"✓ Updated draft act {act_id} with recalculated totals")

    def test_confirm_client_act_changes_status_to_accepted(self):
        """P1: POST /api/client-acts/{id}/confirm changes status to Accepted (earned revenue)"""
        # Create a new draft act to confirm
        create_payload = {
            "project_id": PROJECT_ID,
            "notes": "TEST_Confirm_Act test",
            "lines": [
                {
                    "activity_name": "TEST Confirm Activity",
                    "unit": "m2",
                    "contracted_qty": 50,
                    "executed_qty": 50,
                    "unit_price": 10.0
                }
            ]
        }
        create_response = requests.post(f"{BASE_URL}/api/client-acts", json=create_payload, headers=self.headers)
        assert create_response.status_code == 201
        act = create_response.json()
        act_id = act["id"]
        
        assert act["status"] == "Draft"
        
        # Confirm the act
        confirm_response = requests.post(f"{BASE_URL}/api/client-acts/{act_id}/confirm", headers=self.headers)
        assert confirm_response.status_code == 200, f"Failed to confirm act: {confirm_response.text}"
        
        confirmed_act = confirm_response.json()
        assert confirmed_act["status"] == "Accepted"
        assert "accepted_at" in confirmed_act
        assert "accepted_by" in confirmed_act
        print(f"✓ Confirmed client act {act_id}: status changed to Accepted")

    def test_create_act_from_offer_with_percent(self):
        """P1: POST /api/client-acts/from-offer/{id} generates act from accepted offer with percent parameter"""
        # First, get available offers for the project
        offers_response = requests.get(f"{BASE_URL}/api/offers", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert offers_response.status_code == 200
        offers = offers_response.json()
        
        # Find an accepted offer with lines
        accepted_offer = None
        for offer in offers:
            if offer.get("status") == "Accepted" and offer.get("lines"):
                accepted_offer = offer
                break
        
        if not accepted_offer:
            pytest.skip("No accepted offer with lines available")
        
        offer_id = accepted_offer["id"]
        
        # Create act from offer with 50% execution
        response = requests.post(
            f"{BASE_URL}/api/client-acts/from-offer/{offer_id}",
            json={"percent": 50, "period_from": "2026-01-01", "period_to": "2026-01-15"},
            headers=self.headers
        )
        assert response.status_code == 201, f"Failed to create act from offer: {response.text}"
        
        act = response.json()
        assert act["status"] == "Draft"
        assert act["source_offer_id"] == offer_id
        assert act["project_id"] == accepted_offer["project_id"]
        
        # Verify lines have 50% execution
        for line in act["lines"]:
            assert line["executed_percent"] == 50
            assert "offer_line_id" in line
        
        print(f"✓ Created act from offer {offer_id} with 50% execution")


class TestRevenueExpensePhase2LaborCost:
    """Phase 2: Labor Cost Aggregation tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        self.token = data.get("access_token") or data.get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_get_labor_cost_by_project(self):
        """P2: GET /api/labor-cost/by-project/{id} returns hours × rate aggregation"""
        response = requests.get(f"{BASE_URL}/api/labor-cost/by-project/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200, f"Failed to get labor cost: {response.text}"
        
        data = response.json()
        assert data["project_id"] == PROJECT_ID
        assert "total_hours" in data
        assert "total_cost" in data
        assert "currency" in data
        assert "by_employee" in data
        assert "by_activity" in data
        assert "data_source" in data
        assert data["data_source"] == "work_reports × employee_profiles.hourly_rate"
        print(f"✓ Labor cost summary: {data['total_hours']} hours, {data['total_cost']} {data['currency']}")

    def test_labor_cost_returns_employee_breakdown(self):
        """P2: Labor cost returns by_employee breakdown"""
        response = requests.get(f"{BASE_URL}/api/labor-cost/by-project/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        by_employee = data.get("by_employee", [])
        
        # Verify structure of by_employee breakdown
        assert isinstance(by_employee, list)
        for emp in by_employee:
            assert "user_id" in emp
            assert "name" in emp
            assert "hourly_rate" in emp
            assert "hours" in emp
            assert "cost" in emp
        print(f"✓ by_employee breakdown has {len(by_employee)} entries")

    def test_labor_cost_returns_activity_breakdown(self):
        """P2: Labor cost returns by_activity breakdown"""
        response = requests.get(f"{BASE_URL}/api/labor-cost/by-project/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        by_activity = data.get("by_activity", [])
        
        # Verify structure of by_activity breakdown
        assert isinstance(by_activity, list)
        for act in by_activity:
            assert "activity_name" in act
            assert "hours" in act
            assert "cost" in act
        print(f"✓ by_activity breakdown has {len(by_activity)} entries")


class TestRevenueExpensePhase3ExecutionPackages:
    """Phase 3: Execution Packages tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        self.token = data.get("access_token") or data.get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_get_execution_packages_by_project(self):
        """P3: GET /api/execution-packages?project_id returns packages"""
        response = requests.get(f"{BASE_URL}/api/execution-packages", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert response.status_code == 200, f"Failed to get execution packages: {response.text}"
        
        packages = response.json()
        assert isinstance(packages, list)
        
        # Verify package structure
        for pkg in packages:
            assert "id" in pkg
            assert "project_id" in pkg
            assert "activity_name" in pkg
            assert "unit" in pkg
            assert "qty" in pkg
            assert "sale_unit_price" in pkg
            assert "sale_total" in pkg
            assert "status" in pkg
        
        print(f"✓ Found {len(packages)} execution packages for project {PROJECT_ID}")

    def test_update_execution_package_progress(self):
        """P3: PUT /api/execution-packages/{id} updates progress/actuals"""
        # First get existing packages
        response = requests.get(f"{BASE_URL}/api/execution-packages", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert response.status_code == 200
        packages = response.json()
        
        if not packages:
            pytest.skip("No execution packages available to update")
        
        pkg_id = packages[0]["id"]
        
        # Update progress and actuals
        update_payload = {
            "progress_percent": 75,
            "qty_executed": 50,
            "used_hours": 20,
            "actual_material_cost": 500.0,
            "actual_labor_cost": 300.0,
            "status": "InProgress"
        }
        
        response = requests.put(f"{BASE_URL}/api/execution-packages/{pkg_id}", json=update_payload, headers=self.headers)
        assert response.status_code == 200, f"Failed to update package: {response.text}"
        
        updated_pkg = response.json()
        assert updated_pkg["progress_percent"] == 75
        assert updated_pkg["qty_executed"] == 50
        assert updated_pkg["used_hours"] == 20
        assert updated_pkg["actual_material_cost"] == 500.0
        assert updated_pkg["actual_labor_cost"] == 300.0
        
        # Verify actual_total_cost is calculated
        assert updated_pkg["actual_total_cost"] == 800.0  # 500 + 300
        print(f"✓ Updated execution package {pkg_id} with progress and actuals")

    def test_generate_packages_from_offer(self):
        """P3: POST /api/execution-packages/from-offer/{id} generates packages from offer lines"""
        # First get offers to find one without packages
        offers_response = requests.get(f"{BASE_URL}/api/offers", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert offers_response.status_code == 200
        offers = offers_response.json()
        
        # Find an offer that might not have packages yet
        for offer in offers:
            if offer.get("status") == "Accepted" and offer.get("lines"):
                offer_id = offer["id"]
                
                # Check if packages already exist for this offer
                pkg_response = requests.get(f"{BASE_URL}/api/execution-packages", params={"offer_id": offer_id}, headers=self.headers)
                existing_pkgs = pkg_response.json()
                
                if not existing_pkgs:
                    # Generate packages
                    response = requests.post(f"{BASE_URL}/api/execution-packages/from-offer/{offer_id}", headers=self.headers)
                    assert response.status_code == 201, f"Failed to generate packages: {response.text}"
                    
                    result = response.json()
                    assert result["ok"] == True
                    assert result["offer_id"] == offer_id
                    assert result["count"] >= 1
                    print(f"✓ Generated {result['count']} execution packages from offer {offer_id}")
                    return
        
        # All accepted offers already have packages - test passes
        print("✓ All accepted offers already have execution packages")

    def test_duplicate_package_generation_prevented(self):
        """P3: Duplicate generation prevented (returns 400)"""
        # Get offers with existing packages
        offers_response = requests.get(f"{BASE_URL}/api/offers", params={"project_id": PROJECT_ID}, headers=self.headers)
        assert offers_response.status_code == 200
        offers = offers_response.json()
        
        offer_with_packages = None
        for offer in offers:
            if offer.get("status") == "Accepted":
                offer_id = offer["id"]
                pkg_response = requests.get(f"{BASE_URL}/api/execution-packages", params={"offer_id": offer_id}, headers=self.headers)
                if pkg_response.json():
                    offer_with_packages = offer_id
                    break
        
        if not offer_with_packages:
            pytest.skip("No offer with existing packages found")
        
        # Try to generate packages again - should fail with 400
        response = requests.post(f"{BASE_URL}/api/execution-packages/from-offer/{offer_with_packages}", headers=self.headers)
        assert response.status_code == 400, f"Expected 400 for duplicate generation, got {response.status_code}"
        
        error = response.json()
        assert "already exist" in error.get("detail", "").lower()
        print(f"✓ Duplicate package generation correctly prevented with 400 error")


class TestRevenueExpensePhase4ProjectProfit:
    """Phase 4: Project Profit Summary tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        self.token = data.get("access_token") or data.get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_get_project_profit_summary(self):
        """P4: GET /api/project-profit/{id} returns revenue/expenses/profit summary"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200, f"Failed to get project profit: {response.text}"
        
        data = response.json()
        assert data["project_id"] == PROJECT_ID
        assert "project_code" in data
        assert "project_name" in data
        assert "currency" in data
        
        # Verify main sections exist
        assert "revenue" in data
        assert "expenses" in data
        assert "profit" in data
        assert "metrics_available" in data
        print(f"✓ Project profit summary retrieved for {data['project_code']}")

    def test_revenue_has_all_stages(self):
        """P4: Revenue has contracted/earned/billed/collected stages"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        revenue = data["revenue"]
        
        assert "contracted" in revenue
        assert "earned" in revenue
        assert "billed" in revenue
        assert "collected" in revenue
        assert "receivables" in revenue
        
        print(f"✓ Revenue stages: contracted={revenue['contracted']}, earned={revenue['earned']}, "
              f"billed={revenue['billed']}, collected={revenue['collected']}")

    def test_expenses_has_category_breakdown(self):
        """P4: Expenses has material/labor/subcontract/overhead breakdown"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        expenses = data["expenses"]
        
        assert "material" in expenses
        assert "labor" in expenses
        assert "subcontract" in expenses
        assert "overhead" in expenses
        assert "total" in expenses
        
        # Verify total is sum of components
        calculated_total = (
            expenses["material"] +
            expenses["labor"] +
            expenses["subcontract"] +
            expenses["overhead"]
        )
        assert abs(expenses["total"] - calculated_total) < 0.01
        
        print(f"✓ Expenses breakdown: material={expenses['material']}, labor={expenses['labor']}, "
              f"subcontract={expenses['subcontract']}, overhead={expenses['overhead']}")

    def test_metrics_available_flags(self):
        """P4: metrics_available flags show which data sources exist"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        metrics = data["metrics_available"]
        
        # All expected flags should be present
        expected_flags = [
            "contracted_revenue",
            "earned_revenue",
            "billed_revenue",
            "material_cost",
            "labor_cost",
            "subcontract_cost",
            "overhead_cost",
            "execution_packages"
        ]
        
        for flag in expected_flags:
            assert flag in metrics, f"Missing flag: {flag}"
            assert isinstance(metrics[flag], bool)
        
        print(f"✓ metrics_available flags present: {metrics}")

    def test_profit_uses_earned_revenue_when_available(self):
        """P4: Profit calculation uses earned revenue when available, contracted as fallback"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        profit = data["profit"]
        revenue = data["revenue"]
        
        assert "gross_profit" in profit
        assert "gross_margin_percent" in profit
        assert "revenue_basis" in profit
        
        # Verify revenue_basis logic
        if revenue["earned"] > 0:
            assert profit["revenue_basis"] == "earned"
            expected_gross = revenue["earned"] - data["expenses"]["total"]
        else:
            assert profit["revenue_basis"] == "contracted"
            expected_gross = revenue["contracted"] - data["expenses"]["total"]
        
        assert abs(profit["gross_profit"] - expected_gross) < 0.01
        
        print(f"✓ Profit calculation: gross_profit={profit['gross_profit']}, "
              f"margin={profit['gross_margin_percent']}%, basis={profit['revenue_basis']}")

    def test_execution_packages_breakdown_in_profit(self):
        """P4: Project profit includes execution packages breakdown"""
        response = requests.get(f"{BASE_URL}/api/project-profit/{PROJECT_ID}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        packages = data.get("execution_packages", [])
        
        # Verify structure of each package
        for pkg in packages:
            assert "id" in pkg
            assert "activity_name" in pkg
            assert "sale_total" in pkg
            assert "budget_total" in pkg
            assert "actual_total_cost" in pkg
            assert "progress_percent" in pkg
            assert "status" in pkg
        
        print(f"✓ Execution packages in profit summary: {len(packages)} packages")


class TestRevenueExpenseEdgeCases:
    """Edge case and error handling tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        self.token = data.get("access_token") or data.get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_get_act_not_found(self):
        """Returns 404 for non-existent act"""
        response = requests.get(f"{BASE_URL}/api/client-acts/non-existent-id", headers=self.headers)
        assert response.status_code == 404

    def test_update_non_draft_act_fails(self):
        """Cannot update non-draft act"""
        # Get an accepted act
        response = requests.get(f"{BASE_URL}/api/client-acts", params={"project_id": PROJECT_ID}, headers=self.headers)
        acts = response.json()
        
        accepted_act = None
        for act in acts:
            if act["status"] == "Accepted":
                accepted_act = act
                break
        
        if not accepted_act:
            pytest.skip("No accepted act to test")
        
        # Try to update - should fail
        response = requests.put(
            f"{BASE_URL}/api/client-acts/{accepted_act['id']}", 
            json={"notes": "Should fail"},
            headers=self.headers
        )
        assert response.status_code == 400
        print("✓ Cannot update non-draft act (returns 400)")

    def test_confirm_act_without_lines_fails(self):
        """Cannot confirm act without lines"""
        # Create act without lines
        create_response = requests.post(
            f"{BASE_URL}/api/client-acts",
            json={"project_id": PROJECT_ID, "lines": []},
            headers=self.headers
        )
        assert create_response.status_code == 201
        act_id = create_response.json()["id"]
        
        # Try to confirm - should fail
        confirm_response = requests.post(f"{BASE_URL}/api/client-acts/{act_id}/confirm", headers=self.headers)
        assert confirm_response.status_code == 400
        assert "no lines" in confirm_response.json().get("detail", "").lower()
        print("✓ Cannot confirm act without lines (returns 400)")

    def test_project_profit_not_found(self):
        """Returns 404 for non-existent project"""
        response = requests.get(f"{BASE_URL}/api/project-profit/non-existent-id", headers=self.headers)
        assert response.status_code == 404

    def test_execution_package_not_found(self):
        """Returns 404 for non-existent package"""
        response = requests.put(
            f"{BASE_URL}/api/execution-packages/non-existent-id",
            json={"progress_percent": 50},
            headers=self.headers
        )
        assert response.status_code == 404

    def test_offer_not_found_for_act_creation(self):
        """Returns 404 when creating act from non-existent offer"""
        response = requests.post(
            f"{BASE_URL}/api/client-acts/from-offer/non-existent-id",
            json={"percent": 100},
            headers=self.headers
        )
        assert response.status_code == 404

    def test_offer_not_found_for_package_generation(self):
        """Returns 404 when generating packages from non-existent offer"""
        response = requests.post(
            f"{BASE_URL}/api/execution-packages/from-offer/non-existent-id",
            headers=self.headers
        )
        assert response.status_code == 404
