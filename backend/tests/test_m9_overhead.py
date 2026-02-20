"""
M9 Overhead Cost System Tests
Tests for overhead categories, costs, assets, snapshots, allocations, and permissions
"""
import pytest
import requests
import os
from datetime import datetime

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_TECH_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestOverheadAuth:
    """Test authentication and permission scenarios"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Login as admin user"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200, f"Admin login failed: {resp.text}"
        data = resp.json()
        assert "token" in data
        assert data["user"]["role"] == "Admin"
        print(f"✓ Admin login successful")
        return data["token"]
    
    @pytest.fixture(scope="class")
    def admin_headers(self, admin_token):
        return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    
    def test_admin_can_access_overhead(self, admin_headers):
        """Admin should have full access to overhead system"""
        resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=admin_headers)
        assert resp.status_code == 200, f"Admin overhead access failed: {resp.text}"
        print(f"✓ Admin can access overhead categories: {len(resp.json())} categories")
    
    def test_technician_blocked_from_overhead(self, admin_headers):
        """Technician role should be blocked from overhead system"""
        # First get a technician user to check role restrictions
        resp = requests.get(f"{BASE_URL}/api/users", headers=admin_headers)
        assert resp.status_code == 200
        users = resp.json()
        tech_user = next((u for u in users if u.get("role") == "Technician"), None)
        
        if tech_user:
            # Login as technician and try to access overhead
            tech_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
                "email": tech_user["email"],
                "password": VALID_TECH_PASSWORD
            })
            if tech_resp.status_code == 200:
                tech_token = tech_resp.json()["token"]
                tech_headers = {"Authorization": f"Bearer {tech_token}", "Content-Type": "application/json"}
                overhead_resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=tech_headers)
                assert overhead_resp.status_code == 403, "Technician should be blocked from overhead"
                print(f"✓ Technician correctly blocked from overhead (403)")
            else:
                print(f"⚠ Technician login failed - skipping permission test")
        else:
            print(f"⚠ No technician user found - skipping permission test")


class TestOverheadCategories:
    """Test overhead category CRUD operations"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_list_categories(self, admin_headers):
        """List all overhead categories"""
        resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=admin_headers)
        assert resp.status_code == 200
        categories = resp.json()
        assert isinstance(categories, list)
        print(f"✓ Listed {len(categories)} categories")
        # Check existing category
        office_rent = next((c for c in categories if c["name"] == "Office Rent"), None)
        if office_rent:
            assert office_rent["active"] == True
            print(f"✓ Found 'Office Rent' category - active: {office_rent['active']}")
    
    def test_create_category(self, admin_headers):
        """Create a new overhead category"""
        cat_data = {
            "name": "TEST_Insurance",
            "active": True
        }
        resp = requests.post(f"{BASE_URL}/api/overhead/categories", headers=admin_headers, json=cat_data)
        assert resp.status_code == 200, f"Create category failed: {resp.text}"
        created = resp.json()
        assert created["name"] == "TEST_Insurance"
        assert created["active"] == True
        assert "id" in created
        print(f"✓ Created category: {created['name']} (id: {created['id']})")
        return created["id"]
    
    def test_update_category(self, admin_headers):
        """Update an existing category"""
        # Create category to update
        create_resp = requests.post(f"{BASE_URL}/api/overhead/categories", headers=admin_headers, json={
            "name": "TEST_ToUpdate",
            "active": True
        })
        assert create_resp.status_code == 200
        cat_id = create_resp.json()["id"]
        
        # Update it
        update_resp = requests.put(f"{BASE_URL}/api/overhead/categories/{cat_id}", headers=admin_headers, json={
            "name": "TEST_Updated",
            "active": False
        })
        assert update_resp.status_code == 200, f"Update failed: {update_resp.text}"
        updated = update_resp.json()
        assert updated["name"] == "TEST_Updated"
        assert updated["active"] == False
        print(f"✓ Updated category: {updated['name']} (active: {updated['active']})")
        
        # Clean up
        requests.delete(f"{BASE_URL}/api/overhead/categories/{cat_id}", headers=admin_headers)
    
    def test_delete_category(self, admin_headers):
        """Delete a category"""
        # Create category to delete
        create_resp = requests.post(f"{BASE_URL}/api/overhead/categories", headers=admin_headers, json={
            "name": "TEST_ToDelete",
            "active": True
        })
        assert create_resp.status_code == 200
        cat_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(f"{BASE_URL}/api/overhead/categories/{cat_id}", headers=admin_headers)
        assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
        
        # Verify deletion
        list_resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=admin_headers)
        categories = list_resp.json()
        deleted_cat = next((c for c in categories if c["id"] == cat_id), None)
        assert deleted_cat is None, "Category should be deleted"
        print(f"✓ Deleted category successfully")


class TestOverheadCosts:
    """Test overhead cost CRUD operations"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    @pytest.fixture(scope="class")
    def category_id(self, admin_headers):
        """Get existing category ID"""
        resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=admin_headers)
        categories = resp.json()
        if categories:
            return categories[0]["id"]
        # Create one if none exists
        create_resp = requests.post(f"{BASE_URL}/api/overhead/categories", headers=admin_headers, json={
            "name": "TEST_CostCategory",
            "active": True
        })
        return create_resp.json()["id"]
    
    def test_list_costs(self, admin_headers):
        """List overhead costs"""
        resp = requests.get(f"{BASE_URL}/api/overhead/costs", headers=admin_headers)
        assert resp.status_code == 200
        costs = resp.json()
        assert isinstance(costs, list)
        print(f"✓ Listed {len(costs)} costs")
        # Check existing cost
        if costs:
            cost = costs[0]
            assert "name" in cost
            assert "amount" in cost
            assert "frequency" in cost
            print(f"✓ Sample cost: {cost['name']} - €{cost['amount']}")
    
    def test_list_costs_with_date_filter(self, admin_headers):
        """List costs with date filter"""
        resp = requests.get(f"{BASE_URL}/api/overhead/costs?date_from=2026-02-01&date_to=2026-02-28", headers=admin_headers)
        assert resp.status_code == 200
        costs = resp.json()
        print(f"✓ Listed {len(costs)} costs in Feb 2026")
    
    def test_create_cost(self, admin_headers, category_id):
        """Create a new overhead cost"""
        cost_data = {
            "category_id": category_id,
            "name": "TEST_Utilities",
            "amount": 500.00,
            "vat_percent": 20.0,
            "date_incurred": "2026-02-15",
            "frequency": "Monthly",
            "allocation_type": "CompanyWide",
            "note": "Test utility cost"
        }
        resp = requests.post(f"{BASE_URL}/api/overhead/costs", headers=admin_headers, json=cost_data)
        assert resp.status_code == 200, f"Create cost failed: {resp.text}"
        created = resp.json()
        assert created["name"] == "TEST_Utilities"
        assert created["amount"] == 500.00
        assert created["frequency"] == "Monthly"
        assert created["allocation_type"] == "CompanyWide"
        print(f"✓ Created cost: {created['name']} - €{created['amount']}")
        return created["id"]
    
    def test_create_cost_all_frequencies(self, admin_headers, category_id):
        """Test creating costs with different frequencies"""
        frequencies = ["OneTime", "Monthly", "Weekly"]
        for freq in frequencies:
            cost_data = {
                "category_id": category_id,
                "name": f"TEST_{freq}_Cost",
                "amount": 100.00,
                "date_incurred": "2026-02-15",
                "frequency": freq,
                "allocation_type": "CompanyWide"
            }
            resp = requests.post(f"{BASE_URL}/api/overhead/costs", headers=admin_headers, json=cost_data)
            assert resp.status_code == 200, f"Create {freq} cost failed: {resp.text}"
            print(f"✓ Created {freq} cost")
            # Clean up
            requests.delete(f"{BASE_URL}/api/overhead/costs/{resp.json()['id']}", headers=admin_headers)
    
    def test_create_cost_all_allocation_types(self, admin_headers, category_id):
        """Test creating costs with different allocation types"""
        alloc_types = ["CompanyWide", "PerPerson", "PerAssetAmortized"]
        for alloc_type in alloc_types:
            cost_data = {
                "category_id": category_id,
                "name": f"TEST_{alloc_type}_Cost",
                "amount": 100.00,
                "date_incurred": "2026-02-15",
                "frequency": "OneTime",
                "allocation_type": alloc_type
            }
            resp = requests.post(f"{BASE_URL}/api/overhead/costs", headers=admin_headers, json=cost_data)
            assert resp.status_code == 200, f"Create {alloc_type} cost failed: {resp.text}"
            print(f"✓ Created {alloc_type} cost")
            # Clean up
            requests.delete(f"{BASE_URL}/api/overhead/costs/{resp.json()['id']}", headers=admin_headers)
    
    def test_update_cost(self, admin_headers, category_id):
        """Update an existing cost"""
        # Create cost to update
        create_resp = requests.post(f"{BASE_URL}/api/overhead/costs", headers=admin_headers, json={
            "category_id": category_id,
            "name": "TEST_ToUpdateCost",
            "amount": 200.00,
            "date_incurred": "2026-02-15",
            "frequency": "OneTime",
            "allocation_type": "CompanyWide"
        })
        assert create_resp.status_code == 200
        cost_id = create_resp.json()["id"]
        
        # Update it
        update_resp = requests.put(f"{BASE_URL}/api/overhead/costs/{cost_id}", headers=admin_headers, json={
            "name": "TEST_UpdatedCost",
            "amount": 300.00
        })
        assert update_resp.status_code == 200, f"Update failed: {update_resp.text}"
        updated = update_resp.json()
        assert updated["name"] == "TEST_UpdatedCost"
        assert updated["amount"] == 300.00
        print(f"✓ Updated cost: {updated['name']} - €{updated['amount']}")
        
        # Clean up
        requests.delete(f"{BASE_URL}/api/overhead/costs/{cost_id}", headers=admin_headers)
    
    def test_delete_cost(self, admin_headers, category_id):
        """Delete a cost"""
        # Create cost to delete
        create_resp = requests.post(f"{BASE_URL}/api/overhead/costs", headers=admin_headers, json={
            "category_id": category_id,
            "name": "TEST_ToDeleteCost",
            "amount": 100.00,
            "date_incurred": "2026-02-15",
            "frequency": "OneTime",
            "allocation_type": "CompanyWide"
        })
        assert create_resp.status_code == 200
        cost_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(f"{BASE_URL}/api/overhead/costs/{cost_id}", headers=admin_headers)
        assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
        print(f"✓ Deleted cost successfully")


class TestOverheadAssets:
    """Test overhead asset CRUD operations"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_list_assets(self, admin_headers):
        """List overhead assets"""
        resp = requests.get(f"{BASE_URL}/api/overhead/assets?active_only=false", headers=admin_headers)
        assert resp.status_code == 200
        assets = resp.json()
        assert isinstance(assets, list)
        print(f"✓ Listed {len(assets)} assets")
    
    def test_create_asset(self, admin_headers):
        """Create a new amortizable asset"""
        asset_data = {
            "name": "TEST_Laptop",
            "purchase_cost": 1200.00,
            "purchase_date": "2026-01-01",
            "useful_life_months": 36,
            "active": True,
            "note": "Development laptop"
        }
        resp = requests.post(f"{BASE_URL}/api/overhead/assets", headers=admin_headers, json=asset_data)
        assert resp.status_code == 200, f"Create asset failed: {resp.text}"
        created = resp.json()
        assert created["name"] == "TEST_Laptop"
        assert created["purchase_cost"] == 1200.00
        assert created["useful_life_months"] == 36
        assert created["active"] == True
        # Verify daily amortization calculation
        expected_daily = 1200.00 / (36 * 30.4375)  # ~1.095 per day
        assert "daily_amortization" in created
        assert abs(created["daily_amortization"] - expected_daily) < 0.01
        print(f"✓ Created asset: {created['name']} - €{created['purchase_cost']} (daily amort: €{created['daily_amortization']:.2f})")
        return created["id"]
    
    def test_update_asset(self, admin_headers):
        """Update an existing asset"""
        # Create asset to update
        create_resp = requests.post(f"{BASE_URL}/api/overhead/assets", headers=admin_headers, json={
            "name": "TEST_ToUpdateAsset",
            "purchase_cost": 500.00,
            "purchase_date": "2026-01-01",
            "useful_life_months": 24,
            "active": True
        })
        assert create_resp.status_code == 200
        asset_id = create_resp.json()["id"]
        
        # Update it
        update_resp = requests.put(f"{BASE_URL}/api/overhead/assets/{asset_id}", headers=admin_headers, json={
            "name": "TEST_UpdatedAsset",
            "purchase_cost": 600.00,
            "active": False
        })
        assert update_resp.status_code == 200, f"Update failed: {update_resp.text}"
        updated = update_resp.json()
        assert updated["name"] == "TEST_UpdatedAsset"
        assert updated["purchase_cost"] == 600.00
        assert updated["active"] == False
        print(f"✓ Updated asset: {updated['name']} (active: {updated['active']})")
        
        # Clean up
        requests.delete(f"{BASE_URL}/api/overhead/assets/{asset_id}", headers=admin_headers)
    
    def test_delete_asset(self, admin_headers):
        """Delete an asset"""
        # Create asset to delete
        create_resp = requests.post(f"{BASE_URL}/api/overhead/assets", headers=admin_headers, json={
            "name": "TEST_ToDeleteAsset",
            "purchase_cost": 300.00,
            "purchase_date": "2026-01-01",
            "useful_life_months": 12,
            "active": True
        })
        assert create_resp.status_code == 200
        asset_id = create_resp.json()["id"]
        
        # Delete it
        delete_resp = requests.delete(f"{BASE_URL}/api/overhead/assets/{asset_id}", headers=admin_headers)
        assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
        print(f"✓ Deleted asset successfully")


class TestOverheadSnapshots:
    """Test overhead snapshot computation"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_list_snapshots(self, admin_headers):
        """List overhead snapshots"""
        resp = requests.get(f"{BASE_URL}/api/overhead/snapshots", headers=admin_headers)
        assert resp.status_code == 200
        snapshots = resp.json()
        assert isinstance(snapshots, list)
        print(f"✓ Listed {len(snapshots)} snapshots")
        
        # Check existing snapshot
        if snapshots:
            snap = snapshots[0]
            assert "total_overhead" in snap
            assert "total_person_days" in snap
            assert "overhead_rate_per_person_day" in snap
            print(f"✓ Sample snapshot: period {snap['period_start']} to {snap['period_end']}")
            print(f"  Total: €{snap['total_overhead']}, PersonDays: {snap['total_person_days']}, Rate: €{snap['overhead_rate_per_person_day']}/person-day")
    
    def test_get_snapshot_detail(self, admin_headers):
        """Get snapshot detail with allocations"""
        # Get existing snapshot
        list_resp = requests.get(f"{BASE_URL}/api/overhead/snapshots", headers=admin_headers)
        snapshots = list_resp.json()
        
        if snapshots:
            snap_id = snapshots[0]["id"]
            detail_resp = requests.get(f"{BASE_URL}/api/overhead/snapshots/{snap_id}", headers=admin_headers)
            assert detail_resp.status_code == 200, f"Get snapshot detail failed: {detail_resp.text}"
            detail = detail_resp.json()
            assert "allocations" in detail
            print(f"✓ Got snapshot detail with {len(detail['allocations'])} allocations")
        else:
            print("⚠ No snapshots to test detail")
    
    def test_compute_snapshot_person_days(self, admin_headers):
        """Compute a new snapshot using PersonDays method"""
        resp = requests.post(f"{BASE_URL}/api/overhead/snapshots/compute", headers=admin_headers, json={
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "method": "PersonDays",
            "notes": "TEST snapshot"
        })
        assert resp.status_code == 200, f"Compute snapshot failed: {resp.text}"
        snapshot = resp.json()
        
        # Verify snapshot structure
        assert "id" in snapshot
        assert "total_overhead" in snapshot
        assert "total_costs" in snapshot
        assert "total_amortization" in snapshot
        assert "total_person_days" in snapshot
        assert "overhead_rate_per_person_day" in snapshot
        assert snapshot["method"] == "PersonDays"
        
        print(f"✓ Computed snapshot:")
        print(f"  Total Overhead: €{snapshot['total_overhead']}")
        print(f"  Total Costs: €{snapshot['total_costs']}")
        print(f"  Total Amortization: €{snapshot['total_amortization']}")
        print(f"  Person Days: {snapshot['total_person_days']}")
        print(f"  Rate/Person-Day: €{snapshot['overhead_rate_per_person_day']}")
    
    def test_compute_snapshot_hours(self, admin_headers):
        """Compute a snapshot using Hours method"""
        resp = requests.post(f"{BASE_URL}/api/overhead/snapshots/compute", headers=admin_headers, json={
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "method": "Hours",
            "notes": "TEST hours snapshot"
        })
        assert resp.status_code == 200, f"Compute snapshot failed: {resp.text}"
        snapshot = resp.json()
        assert snapshot["method"] == "Hours"
        assert "total_hours" in snapshot
        assert "overhead_rate_per_hour" in snapshot
        print(f"✓ Computed Hours snapshot - Hours: {snapshot['total_hours']}, Rate: €{snapshot['overhead_rate_per_hour']}/hour")


class TestOverheadAllocation:
    """Test overhead allocation to projects"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_allocate_to_projects(self, admin_headers):
        """Allocate overhead to projects"""
        # Get existing snapshot
        list_resp = requests.get(f"{BASE_URL}/api/overhead/snapshots", headers=admin_headers)
        snapshots = list_resp.json()
        
        if not snapshots:
            print("⚠ No snapshots to test allocation")
            return
        
        snap_id = snapshots[0]["id"]
        total_person_days = snapshots[0].get("total_person_days", 0)
        
        if total_person_days == 0:
            print("⚠ Snapshot has 0 person-days, skipping allocation test")
            return
        
        # Allocate using PersonDays method
        alloc_resp = requests.post(f"{BASE_URL}/api/overhead/snapshots/{snap_id}/allocate", headers=admin_headers, json={
            "method": "PersonDays"
        })
        assert alloc_resp.status_code == 200, f"Allocation failed: {alloc_resp.text}"
        result = alloc_resp.json()
        assert "allocations" in result
        
        print(f"✓ Allocated overhead to {len(result['allocations'])} projects")
        for alloc in result["allocations"]:
            print(f"  - {alloc.get('project_code', 'N/A')}: €{alloc['allocated_amount']} ({alloc['basis_person_days']} person-days)")
    
    def test_list_allocations(self, admin_headers):
        """List all allocations"""
        resp = requests.get(f"{BASE_URL}/api/overhead/allocations", headers=admin_headers)
        assert resp.status_code == 200
        allocations = resp.json()
        assert isinstance(allocations, list)
        print(f"✓ Listed {len(allocations)} allocations")


class TestOverheadEnums:
    """Test overhead enum endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_get_enums(self, admin_headers):
        """Get overhead enums"""
        resp = requests.get(f"{BASE_URL}/api/overhead/enums", headers=admin_headers)
        assert resp.status_code == 200
        enums = resp.json()
        
        assert "frequencies" in enums
        assert "allocation_types" in enums
        assert "methods" in enums
        
        assert set(enums["frequencies"]) == {"OneTime", "Monthly", "Weekly"}
        assert set(enums["allocation_types"]) == {"CompanyWide", "PerPerson", "PerAssetAmortized"}
        assert set(enums["methods"]) == {"PersonDays", "Hours"}
        
        print(f"✓ Got overhead enums:")
        print(f"  Frequencies: {enums['frequencies']}")
        print(f"  Allocation Types: {enums['allocation_types']}")
        print(f"  Methods: {enums['methods']}")


class TestCleanup:
    """Clean up test data"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": VALID_ADMIN_PASSWORD
        })
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['token']}", "Content-Type": "application/json"}
    
    def test_cleanup_test_data(self, admin_headers):
        """Clean up TEST_ prefixed data"""
        # Clean up categories
        cat_resp = requests.get(f"{BASE_URL}/api/overhead/categories", headers=admin_headers)
        for cat in cat_resp.json():
            if cat["name"].startswith("TEST_"):
                requests.delete(f"{BASE_URL}/api/overhead/categories/{cat['id']}", headers=admin_headers)
                print(f"  Cleaned up category: {cat['name']}")
        
        # Clean up costs
        cost_resp = requests.get(f"{BASE_URL}/api/overhead/costs", headers=admin_headers)
        for cost in cost_resp.json():
            if cost["name"].startswith("TEST_"):
                requests.delete(f"{BASE_URL}/api/overhead/costs/{cost['id']}", headers=admin_headers)
                print(f"  Cleaned up cost: {cost['name']}")
        
        # Clean up assets
        asset_resp = requests.get(f"{BASE_URL}/api/overhead/assets?active_only=false", headers=admin_headers)
        for asset in asset_resp.json():
            if asset["name"].startswith("TEST_"):
                requests.delete(f"{BASE_URL}/api/overhead/assets/{asset['id']}", headers=admin_headers)
                print(f"  Cleaned up asset: {asset['name']}")
        
        print("✓ Cleanup completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
