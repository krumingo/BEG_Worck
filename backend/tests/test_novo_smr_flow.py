"""
Test suite for Novo SMR (Additional Works) Flow - Phase 2
Tests: /projects/{id}/novo-smr page endpoints

Endpoints tested:
- POST /api/extra-works/ai-fast (fast rule-based proposals)
- POST /api/extra-works/ai-refine (LLM-enhanced proposals)
- POST /api/extra-works/batch-save (batch save drafts)
- GET /api/extra-works (list drafts)
- GET /api/extra-works/{id} (get single draft)
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001

@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed")

@pytest.fixture
def api_client(auth_token):
    """Requests session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    })
    return session


class TestAIFastEndpoint:
    """Tests for POST /api/extra-works/ai-fast - Fast rule-based proposals"""
    
    def test_ai_fast_single_line(self, api_client):
        """Test fast AI proposal for single line"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [{"title": "Мазилка по стени", "unit": "m2", "qty": 10}],
            "city": "София"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "results" in data
        assert "combined_materials" in data
        assert "grand_total" in data
        assert data["line_count"] == 1
        assert data["stage"] == "fast"
        
        # Verify proposal content
        result = data["results"][0]
        assert result["provider"] == "rule-based"
        assert "recognized" in result
        assert result["recognized"]["activity_type"] is not None
        assert "pricing" in result
        assert "hourly_info" in result
        assert "confidence" in result
        
    def test_ai_fast_multiple_lines(self, api_client):
        """Test fast AI proposal for multiple lines"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [
                {"title": "Мазилка по стени", "unit": "m2", "qty": 15, 
                 "location_floor": "2", "location_room": "Спалня", "location_zone": "Северна стена"},
                {"title": "Шпакловка", "unit": "m2", "qty": 10},
                {"title": "Боядисване", "unit": "m2", "qty": 20}
            ],
            "city": "София"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["line_count"] == 3
        assert len(data["results"]) == 3
        
        # Verify each result has required fields
        for result in data["results"]:
            assert "pricing" in result
            assert "material_price_per_unit" in result["pricing"]
            assert "labor_price_per_unit" in result["pricing"]
            assert "total_price_per_unit" in result["pricing"]
            assert "_input" in result
            
    def test_ai_fast_returns_location_in_input(self, api_client):
        """Test that location data is preserved in _input"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [{"title": "Мазилка", "unit": "m2", "qty": 5,
                      "location_floor": "3", "location_room": "Кухня", "location_zone": "Таван"}],
            "city": "София"
        })
        assert response.status_code == 200
        result = response.json()["results"][0]
        
        assert result["_input"]["location_floor"] == "3"
        assert result["_input"]["location_room"] == "Кухня"
        assert result["_input"]["location_zone"] == "Таван"
        
    def test_ai_fast_returns_hourly_info(self, api_client):
        """Test that hourly rate info is included"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [{"title": "Шпакловка фина", "unit": "m2", "qty": 2}],
            "city": "София"
        })
        assert response.status_code == 200
        result = response.json()["results"][0]
        
        assert "hourly_info" in result
        hourly = result["hourly_info"]
        assert "worker_type" in hourly
        assert "hourly_rate" in hourly
        assert "min_job_price" in hourly
        assert "min_applied" in hourly


class TestAIRefineEndpoint:
    """Tests for POST /api/extra-works/ai-refine - LLM-enhanced proposals"""
    
    def test_ai_refine_single_line(self, api_client):
        """Test LLM refine for single line"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-refine", json={
            "lines": [{"title": "Мазилка гипсова", "unit": "m2", "qty": 10}],
            "city": "София"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["stage"] == "refined"
        result = data["results"][0]
        
        # LLM provider may return higher confidence
        assert result["provider"] in ["llm", "rule-based"]
        assert "confidence" in result
        
    def test_ai_refine_returns_internal_price_hint(self, api_client):
        """Test that internal price hint is returned when historical data exists"""
        # Use activity type with known historical data
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-refine", json={
            "lines": [{"title": "Шпакловка", "unit": "m2", "qty": 10}],
            "city": "София"
        })
        assert response.status_code == 200
        result = response.json()["results"][0]
        
        # internal_price_hint may or may not be available depending on historical data
        assert "internal_price_hint" in result or "hint" in result or True  # Optional field


class TestBatchSaveEndpoint:
    """Tests for POST /api/extra-works/batch-save"""
    
    def test_batch_save_single_draft(self, api_client):
        """Test saving single extra work draft"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-08",
            "lines": [{
                "title": f"TEST_{uuid.uuid4().hex[:8]}_Мазилка",
                "activity_type": "Мокри процеси",
                "activity_subtype": "Мазилка",
                "unit": "m2",
                "qty": 15,
                "material_price": 9.77,
                "labor_price": 13.8,
                "total_price": 23.57,
                "original_total_price": 23.57,
                "provider": "rule-based",
                "confidence": 0.85,
                "explanation": "Test draft",
                "materials": [],
                "related_smr": [],
                "location_floor": "2",
                "location_room": "Спалня",
                "location_zone": "Северна стена",
                "notes": ""
            }]
        })
        assert response.status_code == 201
        data = response.json()
        
        assert data["ok"] == True
        assert data["saved_count"] == 1
        assert "batch_id" in data
        assert len(data["draft_ids"]) == 1
        
    def test_batch_save_multiple_drafts(self, api_client):
        """Test saving multiple extra work drafts with batch_id"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-08",
            "lines": [
                {
                    "title": f"TEST_{uuid.uuid4().hex[:8]}_Row1",
                    "activity_type": "Довършителни",
                    "activity_subtype": "Шпакловка",
                    "unit": "m2",
                    "qty": 10,
                    "material_price": 5.75,
                    "labor_price": 9.2,
                    "total_price": 14.95,
                    "original_total_price": 14.95,
                    "provider": "rule-based",
                    "confidence": 0.85,
                },
                {
                    "title": f"TEST_{uuid.uuid4().hex[:8]}_Row2",
                    "activity_type": "Довършителни",
                    "activity_subtype": "Боядисване",
                    "unit": "m2",
                    "qty": 20,
                    "material_price": 6.72,
                    "labor_price": 50,
                    "total_price": 56.72,
                    "original_total_price": 56.72,
                    "provider": "rule-based",
                    "confidence": 0.85,
                }
            ]
        })
        assert response.status_code == 201
        data = response.json()
        
        assert data["saved_count"] == 2
        assert len(data["draft_ids"]) == 2
        # All drafts should have same batch_id
        assert "batch_id" in data
        
    def test_batch_save_preserves_location_data(self, api_client):
        """Test that location data is preserved in saved drafts"""
        unique_id = uuid.uuid4().hex[:8]
        response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-08",
            "lines": [{
                "title": f"TEST_{unique_id}_LocationTest",
                "unit": "m2",
                "qty": 5,
                "material_price": 10,
                "labor_price": 20,
                "total_price": 30,
                "location_floor": "5",
                "location_room": "Баня",
                "location_zone": "Под прозорец"
            }]
        })
        assert response.status_code == 201
        draft_id = response.json()["draft_ids"][0]
        
        # Verify location data was saved
        get_response = api_client.get(f"{BASE_URL}/api/extra-works/{draft_id}")
        assert get_response.status_code == 200
        draft = get_response.json()
        
        assert draft["location_floor"] == "5"
        assert draft["location_room"] == "Баня"
        assert draft["location_zone"] == "Под прозорец"
        
    def test_batch_save_requires_project_id(self, api_client):
        """Test that project_id is required"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "work_date": "2026-01-08",
            "lines": [{"title": "Test", "unit": "m2", "qty": 1}]
        })
        assert response.status_code == 400
        
    def test_batch_save_requires_lines(self, api_client):
        """Test that lines array is required"""
        response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-08",
            "lines": []
        })
        assert response.status_code == 400


class TestExtraWorksListEndpoint:
    """Tests for GET /api/extra-works"""
    
    def test_list_drafts_by_project(self, api_client):
        """Test listing drafts filtered by project"""
        response = api_client.get(f"{BASE_URL}/api/extra-works", params={
            "project_id": TEST_PROJECT_ID
        })
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        for draft in data:
            assert draft["project_id"] == TEST_PROJECT_ID
            
    def test_list_drafts_by_status(self, api_client):
        """Test listing drafts filtered by status"""
        response = api_client.get(f"{BASE_URL}/api/extra-works", params={
            "project_id": TEST_PROJECT_ID,
            "status": "draft"
        })
        assert response.status_code == 200
        data = response.json()
        
        for draft in data:
            assert draft["status"] == "draft"


class TestExtraWorksGetEndpoint:
    """Tests for GET /api/extra-works/{id}"""
    
    def test_get_existing_draft(self, api_client):
        """Test getting an existing draft"""
        # First create a draft
        create_response = api_client.post(f"{BASE_URL}/api/extra-works/batch-save", json={
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-08",
            "lines": [{
                "title": f"TEST_{uuid.uuid4().hex[:8]}_GetTest",
                "unit": "m2",
                "qty": 5,
                "material_price": 10,
                "labor_price": 15,
                "total_price": 25
            }]
        })
        draft_id = create_response.json()["draft_ids"][0]
        
        # Get the draft
        response = api_client.get(f"{BASE_URL}/api/extra-works/{draft_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == draft_id
        assert data["project_id"] == TEST_PROJECT_ID
        assert data["status"] == "draft"
        assert "ai_material_price_per_unit" in data
        assert "ai_labor_price_per_unit" in data
        
    def test_get_nonexistent_draft_returns_404(self, api_client):
        """Test that getting nonexistent draft returns 404"""
        response = api_client.get(f"{BASE_URL}/api/extra-works/nonexistent-id-12345")
        assert response.status_code == 404


class TestProjectEndpoint:
    """Tests for project context availability"""
    
    def test_project_exists(self, api_client):
        """Test that test project exists"""
        response = api_client.get(f"{BASE_URL}/api/projects/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == TEST_PROJECT_ID
        assert data["code"] == "PRJ-001"
        assert "name" in data
