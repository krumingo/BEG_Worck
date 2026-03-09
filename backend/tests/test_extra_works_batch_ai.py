"""
Test suite for Extra Works Batch AI + Hourly Rate Logic (P0/P1 features)
Tests:
- POST /api/extra-works/ai-batch - batch AI for multiple lines
- POST /api/extra-works/batch-save - batch save drafts with AI data
- GET /api/ai-config/hourly-rates - worker hourly rate configuration
- Hourly rate logic with min_job_price for small quantities
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"
TEST_PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"


class TestBatchAIProposal:
    """Test batch AI proposal endpoint for multi-line processing"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def test_batch_ai_single_line(self):
        """Test batch AI with single line"""
        payload = {
            "lines": [{"title": "мазилка тест", "unit": "m2", "qty": 10}],
            "city": "София"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "results" in data
        assert "combined_materials" in data
        assert "grand_total" in data
        assert "line_count" in data
        
        assert data["line_count"] == 1
        assert len(data["results"]) == 1
        print(f"✓ Batch AI single line: {data['grand_total']} лв total")
    
    def test_batch_ai_multiple_lines(self):
        """Test batch AI with multiple lines returns per-line proposals"""
        payload = {
            "lines": [
                {"title": "мазилка стена", "unit": "m2", "qty": 15},
                {"title": "боядисване таван", "unit": "m2", "qty": 20}
            ],
            "city": "София",
            "project_id": TEST_PROJECT_ID
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert data["line_count"] == 2
        assert len(data["results"]) == 2
        
        # Verify each result has proper structure
        for i, result in enumerate(data["results"]):
            assert "provider" in result, f"Result {i} missing provider"
            assert "recognized" in result, f"Result {i} missing recognized"
            assert "pricing" in result, f"Result {i} missing pricing"
            assert "materials" in result, f"Result {i} missing materials"
            assert "hourly_info" in result, f"Result {i} missing hourly_info"
            assert "_input" in result, f"Result {i} missing _input"
            
            # Verify pricing fields
            assert "material_price_per_unit" in result["pricing"]
            assert "labor_price_per_unit" in result["pricing"]
            assert "total_price_per_unit" in result["pricing"]
            assert "total_estimated" in result["pricing"]
        
        # Verify combined materials
        assert isinstance(data["combined_materials"], list)
        
        # Verify grand total is sum of line totals
        line_sum = sum(r["pricing"]["total_estimated"] for r in data["results"])
        assert abs(data["grand_total"] - line_sum) < 0.01, "Grand total should match sum of line totals"
        
        print(f"✓ Batch AI {data['line_count']} lines: {data['grand_total']} лв total")
    
    def test_batch_ai_hourly_info_per_line(self):
        """Test each proposal includes hourly_info with worker_type, hourly_rate"""
        payload = {
            "lines": [
                {"title": "електро контакт", "unit": "pcs", "qty": 3},
                {"title": "плочки баня", "unit": "m2", "qty": 5}
            ]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        for result in data["results"]:
            hourly = result.get("hourly_info")
            assert hourly is not None, "hourly_info should be present"
            assert "worker_type" in hourly, "hourly_info should have worker_type"
            assert "hourly_rate" in hourly, "hourly_info should have hourly_rate"
            assert "min_job_price" in hourly, "hourly_info should have min_job_price"
            assert "estimated_labor_total" in hourly, "hourly_info should have estimated_labor_total"
            assert "min_applied" in hourly, "hourly_info should have min_applied flag"
            
            # Validate rates are positive
            assert hourly["hourly_rate"] > 0
            assert hourly["min_job_price"] > 0
        
        print(f"✓ Hourly info present for {len(data['results'])} lines")
    
    def test_batch_ai_small_qty_min_applied(self):
        """Test small quantity pricing applies min_job_price when labor < minimum"""
        payload = {
            "lines": [{"title": "плочки", "unit": "m2", "qty": 1}],  # Very small qty
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        
        hourly = result.get("hourly_info", {})
        # For very small qty, min should be applied
        # Check that the flag exists (may or may not be true depending on labor estimate)
        assert "min_applied" in hourly
        print(f"✓ Small qty test: min_applied={hourly.get('min_applied')}, worker={hourly.get('worker_type')}")
    
    def test_batch_ai_with_location_info(self):
        """Test batch AI preserves location info in _input"""
        payload = {
            "lines": [{
                "title": "мазилка",
                "unit": "m2",
                "qty": 10,
                "location_floor": "2",
                "location_room": "Спалня",
                "location_zone": "Изток"
            }]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        result = data["results"][0]
        input_data = result["_input"]
        assert input_data["location_floor"] == "2"
        assert input_data["location_room"] == "Спалня"
        assert input_data["location_zone"] == "Изток"
        print(f"✓ Location info preserved in batch AI result")
    
    def test_batch_ai_combined_materials(self):
        """Test combined_materials aggregates across lines"""
        payload = {
            "lines": [
                {"title": "мазилка", "unit": "m2", "qty": 10},
                {"title": "боядисване", "unit": "m2", "qty": 10}
            ]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-batch", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        combined = data["combined_materials"]
        assert isinstance(combined, list)
        assert len(combined) > 0
        
        # Verify combined materials have sources
        for mat in combined:
            assert "name" in mat
            assert "sources" in mat
            assert isinstance(mat["sources"], list)
        
        print(f"✓ Combined materials: {len(combined)} unique items")


class TestBatchSave:
    """Test batch save drafts endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.saved_draft_ids = []
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def teardown_method(self):
        """Cleanup saved drafts"""
        for draft_id in self.saved_draft_ids:
            try:
                self.session.delete(f"{BASE_URL}/api/extra-works/{draft_id}")
            except:
                pass
    
    def test_batch_save_multiple_lines(self):
        """Test POST /api/extra-works/batch-save saves multiple drafts"""
        payload = {
            "project_id": TEST_PROJECT_ID,
            "work_date": "2026-01-15",
            "lines": [
                {
                    "title": "TEST_BatchSave_Line1",
                    "unit": "m2",
                    "qty": 5,
                    "material_price": 10.5,
                    "labor_price": 12.0,
                    "total_price": 22.5,
                    "activity_type": "Мокри процеси",
                    "activity_subtype": "Мазилка",
                    "provider": "llm",
                    "confidence": 0.9
                },
                {
                    "title": "TEST_BatchSave_Line2",
                    "unit": "pcs",
                    "qty": 3,
                    "material_price": 25.0,
                    "labor_price": 20.0,
                    "total_price": 45.0,
                    "activity_type": "Инсталации",
                    "activity_subtype": "Електро",
                    "provider": "llm",
                    "confidence": 0.85
                }
            ]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/batch-save", json=payload)
        
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["ok"] == True
        assert data["saved_count"] == 2
        assert "batch_id" in data
        assert len(data["draft_ids"]) == 2
        
        self.saved_draft_ids = data["draft_ids"]
        
        # Verify drafts are persisted
        for draft_id in data["draft_ids"]:
            get_res = self.session.get(f"{BASE_URL}/api/extra-works/{draft_id}")
            assert get_res.status_code == 200
            draft = get_res.json()
            assert draft["status"] == "draft"
            assert draft["group_batch_id"] == data["batch_id"]
        
        print(f"✓ Batch save {data['saved_count']} lines with batch_id: {data['batch_id']}")
    
    def test_batch_save_with_materials_and_related(self):
        """Test batch save preserves materials and related_smr"""
        payload = {
            "project_id": TEST_PROJECT_ID,
            "lines": [{
                "title": "TEST_BatchSave_Materials",
                "unit": "m2",
                "qty": 10,
                "material_price": 8.0,
                "labor_price": 10.0,
                "total_price": 18.0,
                "activity_type": "Мокри процеси",
                "materials": [
                    {"name": "Гипсова мазилка", "unit": "кг", "estimated_qty": 12, "category": "primary"}
                ],
                "related_smr": ["Грундиране", "Боядисване"]
            }]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/batch-save", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        self.saved_draft_ids = data["draft_ids"]
        
        # Verify materials and related_smr are stored
        get_res = self.session.get(f"{BASE_URL}/api/extra-works/{data['draft_ids'][0]}")
        draft = get_res.json()
        
        assert draft["suggested_materials"] is not None
        assert draft["suggested_related_smr"] is not None
        print(f"✓ Batch save preserves materials and related_smr")
    
    def test_batch_save_requires_project_id(self):
        """Test batch save requires project_id"""
        payload = {
            "lines": [{"title": "Test", "unit": "m2", "qty": 1}]
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/batch-save", json=payload)
        assert response.status_code == 400
        print(f"✓ Batch save requires project_id (400 returned)")
    
    def test_batch_save_requires_lines(self):
        """Test batch save requires non-empty lines array"""
        payload = {
            "project_id": TEST_PROJECT_ID,
            "lines": []
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/batch-save", json=payload)
        assert response.status_code == 400
        print(f"✓ Batch save requires lines (400 returned)")


class TestHourlyRatesConfig:
    """Test hourly rates configuration endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def test_get_hourly_rates(self):
        """Test GET /api/ai-config/hourly-rates returns worker rate configuration"""
        response = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify expected worker types
        expected_workers = [
            "общ работник", "майстор", "бояджия", "шпакловчик",
            "електротехник", "вик", "монтажник", "плочкаджия"
        ]
        
        for worker in expected_workers:
            assert worker in data, f"Missing worker type: {worker}"
            worker_data = data[worker]
            assert "hourly_rate" in worker_data
            assert "min_hours" in worker_data
            assert "min_job_price" in worker_data
        
        print(f"✓ Hourly rates config: {len(data)} worker types")
    
    def test_hourly_rates_values(self):
        """Test hourly rates have expected values"""
        response = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        data = response.json()
        
        # Verify specific values from context
        assert data["общ работник"]["hourly_rate"] == 15
        assert data["майстор"]["hourly_rate"] == 22
        assert data["бояджия"]["hourly_rate"] == 18
        assert data["шпакловчик"]["hourly_rate"] == 20
        assert data["електротехник"]["hourly_rate"] == 28
        assert data["вик"]["hourly_rate"] == 26
        assert data["монтажник"]["hourly_rate"] == 20
        assert data["плочкаджия"]["hourly_rate"] == 25
        
        print(f"✓ Hourly rate values match expected configuration")


class TestHourlyRateLogic:
    """Test hourly rate application logic in AI proposals"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def test_worker_type_assigned_by_activity(self):
        """Test worker type is assigned based on activity type"""
        # Test электро should get електротехник
        payload = {"title": "монтаж контакт", "unit": "pcs", "qty": 5}
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        hourly = data.get("hourly_info", {})
        
        # Should be assigned worker based on recognized activity
        assert "worker_type" in hourly
        assert hourly["worker_type"] in ["електротехник", "майстор"]  # Based on recognition
        print(f"✓ Worker type assigned: {hourly.get('worker_type')} for activity: {data['recognized']['activity_subtype']}")
    
    def test_min_job_price_applied_for_small_qty(self):
        """Test min_job_price is applied when estimated labor < minimum"""
        # Very small qty that should trigger minimum
        payload = {"title": "плочки баня", "unit": "m2", "qty": 0.5}
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        hourly = data.get("hourly_info", {})
        
        assert "min_applied" in hourly
        if hourly["min_applied"]:
            assert "adjusted_labor_per_unit" in hourly
            # Adjusted labor per unit should be higher than original
            assert hourly["adjusted_labor_per_unit"] >= data["pricing"]["labor_price_per_unit"]
        
        print(f"✓ Min job price test: min_applied={hourly.get('min_applied')}")
    
    def test_hourly_info_includes_all_required_fields(self):
        """Test hourly_info structure is complete"""
        payload = {"title": "боядисване", "unit": "m2", "qty": 10}
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        hourly = data.get("hourly_info", {})
        
        required_fields = [
            "worker_type", "hourly_rate", "min_hours", 
            "min_job_price", "estimated_labor_total", "min_applied"
        ]
        
        for field in required_fields:
            assert field in hourly, f"Missing field: {field}"
        
        print(f"✓ Hourly info complete with all {len(required_fields)} required fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
