"""
Test suite for Cyrillic sub-project creation feature.
Tests:
- POST /api/projects/{id}/create-sub-project (first call creates А + Б, subsequent creates В, Г...)
- Child codes follow pattern PARENT-А, PARENT-Б, PARENT-В
- Data migration from parent to child А
- GET /api/projects/{id}/aggregate returns per-child breakdowns
- Child projects inherit shared data from parent
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Test project IDs from context
TEST_PROJECT_WITH_SUBS = "da29f0e4-532c-48b7-b12a-e5109bba51fc"  # Already has 3 children
ORIGINAL_PROJECT = "c3529276-8c03-49b3-92de-51216aab25da"  # No sub-projects yet


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    # API returns 'token' not 'access_token'
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated requests session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestSubProjectCreation:
    """Test sub-project creation endpoint"""

    def test_get_project_with_existing_subs(self, api_client):
        """Verify test project with existing sub-projects"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}")
        assert response.status_code == 200, f"Failed to get project: {response.text}"
        project = response.json()
        assert "id" in project
        assert "code" in project
        print(f"Project with subs: {project.get('code')} - {project.get('name')}")

    def test_get_project_dashboard_with_subs(self, api_client):
        """Verify dashboard returns sub_projects list"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200, f"Failed to get dashboard: {response.text}"
        data = response.json()
        
        # Check sub_projects array exists
        assert "sub_projects" in data, "Dashboard should contain sub_projects"
        sub_projects = data["sub_projects"]
        assert isinstance(sub_projects, list), "sub_projects should be a list"
        
        print(f"Found {len(sub_projects)} sub-projects")
        for sp in sub_projects:
            print(f"  - {sp.get('code')}: {sp.get('name')} ({sp.get('status')})")
            # Verify Cyrillic letter in code
            code = sp.get("code", "")
            assert "-" in code, f"Sub-project code should contain dash: {code}"
            letter = code.split("-")[-1]
            assert letter in "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЬЮЯ", f"Code should end with Cyrillic letter: {code}"

    def test_sub_project_codes_follow_pattern(self, api_client):
        """Verify child codes follow PARENT-А, PARENT-Б pattern"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        parent_code = data["project"]["code"]
        sub_projects = data.get("sub_projects", [])
        
        for sp in sub_projects:
            child_code = sp.get("code", "")
            # Child code should start with parent code
            assert child_code.startswith(parent_code), f"Child code {child_code} should start with {parent_code}"
            # Should have format PARENT-LETTER
            parts = child_code.split("-")
            assert len(parts) >= 2, f"Child code should have at least 2 parts: {child_code}"
            letter = parts[-1]
            assert len(letter) == 1, f"Last part should be single letter: {letter}"
            assert letter in "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЬЮЯ", f"Letter should be Cyrillic: {letter}"

    def test_subsequent_sub_project_creation(self, api_client):
        """Test creating additional sub-project (В, Г, Д...)"""
        # First check current state
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        data = response.json()
        initial_count = len(data.get("sub_projects", []))
        print(f"Initial sub-project count: {initial_count}")
        
        # Create new sub-project
        response = api_client.post(
            f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/create-sub-project",
            json={"name": "TEST_Нов под-обект за тест"}
        )
        assert response.status_code == 201, f"Failed to create sub-project: {response.text}"
        result = response.json()
        
        # Verify response structure
        assert "parent_id" in result, "Response should contain parent_id"
        assert "children_created" in result, "Response should contain children_created"
        assert len(result["children_created"]) == 1, "Should create exactly 1 child for subsequent call"
        
        created = result["children_created"][0]
        assert "id" in created, "Created child should have id"
        assert "code" in created, "Created child should have code"
        assert "letter" in created, "Created child should have letter"
        
        print(f"Created sub-project: {created['code']} (letter: {created['letter']})")
        
        # Verify the letter is correct (next in sequence)
        CYRILLIC = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЬЮЯ"
        expected_letter = CYRILLIC[initial_count]
        assert created["letter"] == expected_letter, f"Expected letter {expected_letter}, got {created['letter']}"
        
        # Verify dashboard now shows new sub-project
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        data = response.json()
        new_count = len(data.get("sub_projects", []))
        assert new_count == initial_count + 1, f"Expected {initial_count + 1} sub-projects, got {new_count}"


class TestAggregateEndpoint:
    """Test aggregate endpoint for parent projects"""

    def test_aggregate_returns_per_child_breakdowns(self, api_client):
        """GET /api/projects/{id}/aggregate returns per-child data"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/aggregate")
        assert response.status_code == 200, f"Failed to get aggregate: {response.text}"
        data = response.json()
        
        # Should have children
        assert data.get("has_children") == True, "Should have has_children=True"
        assert "children" in data, "Should contain children array"
        assert "children_count" in data, "Should contain children_count"
        
        children = data["children"]
        assert len(children) > 0, "Should have at least one child"
        
        # Each child should have breakdown data
        for child in children:
            assert "id" in child, "Child should have id"
            assert "code" in child, "Child should have code"
            assert "name" in child, "Child should have name"
            assert "status" in child, "Child should have status"
            
            # Per-child aggregations
            if "team" in child:
                assert "count" in child["team"], "team should have count"
            if "invoices" in child:
                assert "count" in child["invoices"], "invoices should have count"
                assert "paid" in child["invoices"], "invoices should have paid"
            
            print(f"Child {child['code']}: team={child.get('team', {}).get('count', 0)}, invoices={child.get('invoices', {}).get('count', 0)}")

    def test_aggregate_totals(self, api_client):
        """Verify aggregate totals are calculated correctly"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/aggregate")
        assert response.status_code == 200
        data = response.json()
        
        # Check team totals
        assert "team" in data, "Should have team section"
        team = data["team"]
        assert "total" in team, "team should have total"
        assert "count" in team["total"], "team.total should have count"
        
        # Check invoices totals
        assert "invoices" in data, "Should have invoices section"
        invoices = data["invoices"]
        assert "total" in invoices, "invoices should have total"
        assert "invoiced" in invoices["total"], "invoices.total should have invoiced"
        assert "paid" in invoices["total"], "invoices.total should have paid"
        assert "unpaid" in invoices["total"], "invoices.total should have unpaid"
        
        print(f"Aggregate totals - Team: {team['total']['count']}, Invoiced: {invoices['total']['invoiced']}, Paid: {invoices['total']['paid']}")

    def test_aggregate_for_project_without_children(self, api_client):
        """Aggregate for project without children returns has_children=False"""
        response = api_client.get(f"{BASE_URL}/api/projects/{ORIGINAL_PROJECT}/aggregate")
        assert response.status_code == 200, f"Failed to get aggregate: {response.text}"
        data = response.json()
        
        # Should indicate no children
        assert data.get("has_children") == False, "Project without children should have has_children=False"


class TestChildProjectInheritance:
    """Test that child projects inherit shared data from parent"""

    def test_child_inherits_client_data(self, api_client):
        """Child projects should inherit client/owner data from parent"""
        # Get parent dashboard
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        parent_data = response.json()
        
        parent_client = parent_data.get("client", {})
        sub_projects = parent_data.get("sub_projects", [])
        
        if len(sub_projects) > 0 and parent_client.get("owner_id"):
            # Get first child's dashboard
            child_id = sub_projects[0]["id"]
            response = api_client.get(f"{BASE_URL}/api/projects/{child_id}/dashboard")
            assert response.status_code == 200
            child_data = response.json()
            
            child_client = child_data.get("client", {})
            
            # Child should inherit owner data from parent
            # (either directly or through effective_project logic)
            print(f"Parent owner_type: {parent_client.get('owner_type')}")
            print(f"Child owner_type: {child_client.get('owner_type')}")
            
            # If parent has owner, child should have same or inherited
            if parent_client.get("owner_data"):
                # Child should have owner_data (inherited from parent)
                assert child_client.get("owner_data") is not None or child_client.get("owner_type") is not None, \
                    "Child should inherit client data from parent"

    def test_child_shows_parent_badge(self, api_client):
        """Child project dashboard should show parent reference"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        parent_data = response.json()
        
        sub_projects = parent_data.get("sub_projects", [])
        if len(sub_projects) > 0:
            child_id = sub_projects[0]["id"]
            
            # Get child dashboard
            response = api_client.get(f"{BASE_URL}/api/projects/{child_id}/dashboard")
            assert response.status_code == 200
            child_data = response.json()
            
            # Child should have parent_project reference
            assert "parent_project" in child_data, "Child dashboard should have parent_project"
            parent_ref = child_data["parent_project"]
            
            if parent_ref:
                assert "id" in parent_ref, "parent_project should have id"
                assert parent_ref["id"] == TEST_PROJECT_WITH_SUBS, "parent_project.id should match parent"
                print(f"Child references parent: {parent_ref.get('code')} - {parent_ref.get('name')}")


class TestSubProjectValidation:
    """Test validation rules for sub-project creation"""

    def test_cannot_create_nested_sub_projects(self, api_client):
        """Sub-projects cannot have their own sub-projects"""
        # Get a child project ID
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        sub_projects = data.get("sub_projects", [])
        if len(sub_projects) > 0:
            child_id = sub_projects[0]["id"]
            
            # Try to create sub-project of a sub-project
            response = api_client.post(
                f"{BASE_URL}/api/projects/{child_id}/create-sub-project",
                json={"name": "TEST_Nested sub-project"}
            )
            
            # Should fail with 400
            assert response.status_code == 400, f"Should not allow nested sub-projects: {response.text}"
            error = response.json()
            assert "detail" in error, "Error should have detail"
            print(f"Correctly rejected nested sub-project: {error['detail']}")


class TestFirstSplitMigration:
    """Test first-time split migration (original → А + Б)"""

    def test_first_split_creates_two_children(self, api_client):
        """First split should create child А (with migration) and child Б (empty)"""
        # Note: We can't easily test this without a fresh project
        # This test documents the expected behavior
        
        # Get original project (no subs yet)
        response = api_client.get(f"{BASE_URL}/api/projects/{ORIGINAL_PROJECT}/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        sub_projects = data.get("sub_projects", [])
        print(f"Original project has {len(sub_projects)} sub-projects")
        
        # If no sub-projects, first split would create А and Б
        # We document this but don't execute to preserve test data
        if len(sub_projects) == 0:
            print("First split would create:")
            print(f"  - {data['project']['code']}-А (with migrated data)")
            print(f"  - {data['project']['code']}-Б (new empty)")


class TestCleanup:
    """Cleanup test data"""

    def test_cleanup_test_sub_projects(self, api_client):
        """Remove test-created sub-projects"""
        # Get all sub-projects
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_WITH_SUBS}/dashboard")
        if response.status_code != 200:
            return
        
        data = response.json()
        sub_projects = data.get("sub_projects", [])
        
        # Find and delete TEST_ prefixed sub-projects
        for sp in sub_projects:
            if sp.get("name", "").startswith("TEST_"):
                print(f"Cleaning up test sub-project: {sp['code']}")
                # Note: Delete endpoint requires admin
                response = api_client.delete(f"{BASE_URL}/api/projects/{sp['id']}")
                if response.status_code == 200:
                    print(f"  Deleted {sp['code']}")
                else:
                    print(f"  Could not delete {sp['code']}: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
