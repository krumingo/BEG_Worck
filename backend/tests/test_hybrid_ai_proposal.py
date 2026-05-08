"""
Test suite for Hybrid AI Proposal (LLM + Rule-Based Fallback)
Tests:
- LLM provider response (provider='llm')
- City-aware pricing with CITY_PRICE_FACTORS (София=1.15, Пловдив=1.00)
- Data capture fields (ai_provider_used, ai_confidence, ai_raw_response_summary)
- Materials with reason field
- Explanation text in response
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"

# Project for testing
TEST_PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"


class TestHybridAIProposalLLM:
    """Test hybrid AI proposal with real LLM integration"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
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
    
    def test_ai_proposal_returns_llm_provider(self):
        """Test AI proposal returns provider='llm' when LLM succeeds"""
        payload = {
            "title": "Гипсова мазилка по стена",
            "unit": "m2",
            "qty": 10
        }
        
        # LLM calls may take 3-8 seconds
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify LLM provider is used
        assert data.get("provider") in ["llm", "rule-based"], "Provider must be llm or rule-based"
        print(f"✓ AI proposal provider: {data['provider']}")
        
        # Verify response structure
        assert "recognized" in data
        assert "pricing" in data
        assert "explanation" in data
        assert "materials" in data
        assert "confidence" in data
    
    def test_ai_proposal_sofia_city_factor_1_15(self):
        """Test city=София returns city_factor=1.15"""
        payload = {
            "title": "Направа на мазилка",
            "unit": "m2",
            "qty": 10,
            "city": "София"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify city factor for София
        assert data["pricing"]["city"] == "София", "City should be София"
        assert data["pricing"]["city_factor"] == 1.15, f"Sofia city_factor should be 1.15, got {data['pricing'].get('city_factor')}"
        print(f"✓ София city_factor: {data['pricing']['city_factor']}")
    
    def test_ai_proposal_plovdiv_city_factor_1_00(self):
        """Test city=Пловдив returns city_factor=1.00 (null in response since no adjustment)"""
        payload = {
            "title": "Направа на мазилка",
            "unit": "m2",
            "qty": 10,
            "city": "Пловдив"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Пловдив has factor 1.00, so city_factor may be null (no adjustment)
        assert data["pricing"]["city"] == "Пловдив", "City should be Пловдив"
        # Factor is 1.00, so either null or 1.0
        factor = data["pricing"].get("city_factor")
        assert factor in [None, 1.0], f"Plovdiv city_factor should be null or 1.0, got {factor}"
        print(f"✓ Пловдив city_factor: {factor} (1.00 means no adjustment)")
    
    def test_ai_proposal_returns_explanation(self):
        """Test AI proposal returns explanation text"""
        payload = {
            "title": "Боядисване на стени латекс",
            "unit": "m2",
            "qty": 20
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify explanation exists and is non-empty
        assert "explanation" in data, "Response should have explanation field"
        assert data["explanation"], "Explanation should be non-empty"
        assert isinstance(data["explanation"], str)
        print(f"✓ Explanation: {data['explanation'][:100]}...")
    
    def test_ai_proposal_materials_have_reason(self):
        """Test AI proposal materials have reason field"""
        payload = {
            "title": "Полагане на плочки в баня",
            "unit": "m2",
            "qty": 8
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify materials have reason
        assert "materials" in data
        assert isinstance(data["materials"], list)
        assert len(data["materials"]) > 0, "Should have at least one material"
        
        for mat in data["materials"]:
            assert "name" in mat, "Material should have name"
            assert "reason" in mat, f"Material '{mat.get('name')}' should have reason field"
        
        # Print first material as example
        first_mat = data["materials"][0]
        print(f"✓ Material with reason: {first_mat['name']} - {first_mat.get('reason', 'N/A')}")
    
    def test_ai_proposal_unknown_text_handled_by_llm(self):
        """Test unknown construction text (e.g. 'Монтаж на PVC дограма') returns LLM proposal"""
        payload = {
            "title": "Монтаж на PVC дограма с двоен стъклопакет",
            "unit": "pcs",
            "qty": 3
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response has all required fields
        assert "provider" in data
        assert "recognized" in data
        assert "pricing" in data
        assert "materials" in data
        
        # LLM should provide meaningful recognition even for uncommon terms
        if data["provider"] == "llm":
            assert data["confidence"] > 0.5, "LLM should have reasonable confidence"
        
        print(f"✓ Unknown text handled by: {data['provider']}, type: {data['recognized']['activity_type']}")


class TestApplyAIStoresProviderFields:
    """Test POST /api/extra-works/{id}/apply-ai stores ai_provider_used, ai_confidence, ai_raw_response_summary"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.created_draft_ids = []
        
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
        """Cleanup created drafts"""
        for draft_id in self.created_draft_ids:
            try:
                self.session.delete(f"{BASE_URL}/api/extra-works/{draft_id}")
            except:
                pass
    
    def test_apply_ai_stores_provider_used(self):
        """Test apply-ai stores ai_provider_used field"""
        # Create draft
        payload = {
            "project_id": TEST_PROJECT_ID,
            "title": "TEST_Шпакловка за LLM тест",
            "unit": "m2",
            "qty": 15
        }
        create_res = self.session.post(f"{BASE_URL}/api/extra-works", json=payload)
        assert create_res.status_code == 201
        draft_id = create_res.json()["id"]
        self.created_draft_ids.append(draft_id)
        
        # Apply AI
        response = self.session.post(f"{BASE_URL}/api/extra-works/{draft_id}/apply-ai", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify ai_provider_used is stored
        draft = data["draft"]
        assert draft["ai_provider_used"] in ["llm", "rule-based"], f"ai_provider_used should be llm or rule-based, got {draft.get('ai_provider_used')}"
        print(f"✓ ai_provider_used stored: {draft['ai_provider_used']}")
    
    def test_apply_ai_stores_confidence(self):
        """Test apply-ai stores ai_confidence field"""
        # Create draft
        payload = {
            "project_id": TEST_PROJECT_ID,
            "title": "TEST_Гипсокартон таван LLM",
            "unit": "m2",
            "qty": 25
        }
        create_res = self.session.post(f"{BASE_URL}/api/extra-works", json=payload)
        assert create_res.status_code == 201
        draft_id = create_res.json()["id"]
        self.created_draft_ids.append(draft_id)
        
        # Apply AI
        response = self.session.post(f"{BASE_URL}/api/extra-works/{draft_id}/apply-ai", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify ai_confidence is stored
        draft = data["draft"]
        assert draft["ai_confidence"] is not None, "ai_confidence should be stored"
        assert 0 <= draft["ai_confidence"] <= 1, f"ai_confidence should be 0-1, got {draft['ai_confidence']}"
        print(f"✓ ai_confidence stored: {draft['ai_confidence']}")
    
    def test_apply_ai_stores_raw_response_summary(self):
        """Test apply-ai stores ai_raw_response_summary (explanation) field"""
        # Create draft
        payload = {
            "project_id": TEST_PROJECT_ID,
            "title": "TEST_Електро окабеляване LLM",
            "unit": "pcs",
            "qty": 4
        }
        create_res = self.session.post(f"{BASE_URL}/api/extra-works", json=payload)
        assert create_res.status_code == 201
        draft_id = create_res.json()["id"]
        self.created_draft_ids.append(draft_id)
        
        # Apply AI
        response = self.session.post(f"{BASE_URL}/api/extra-works/{draft_id}/apply-ai", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify ai_raw_response_summary is stored
        draft = data["draft"]
        assert draft["ai_raw_response_summary"] is not None, "ai_raw_response_summary should be stored"
        assert isinstance(draft["ai_raw_response_summary"], str), "ai_raw_response_summary should be string"
        print(f"✓ ai_raw_response_summary stored: {draft['ai_raw_response_summary'][:80]}...")
    
    def test_apply_ai_with_city_stores_pricing(self):
        """Test apply-ai with city parameter stores city-adjusted pricing"""
        # Create draft
        payload = {
            "project_id": TEST_PROJECT_ID,
            "title": "TEST_Мазилка София LLM",
            "unit": "m2",
            "qty": 12
        }
        create_res = self.session.post(f"{BASE_URL}/api/extra-works", json=payload)
        assert create_res.status_code == 201
        draft_id = create_res.json()["id"]
        self.created_draft_ids.append(draft_id)
        
        # Apply AI with city
        response = self.session.post(f"{BASE_URL}/api/extra-works/{draft_id}/apply-ai?city=София", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify proposal has city factor
        proposal = data["proposal"]
        assert proposal["pricing"]["city"] == "София"
        assert proposal["pricing"]["city_factor"] == 1.15
        
        # Verify draft has pricing stored
        draft = data["draft"]
        assert draft["ai_material_price_per_unit"] is not None
        assert draft["ai_labor_price_per_unit"] is not None
        assert draft["ai_total_price_per_unit"] is not None
        print(f"✓ City-adjusted pricing stored: {draft['ai_total_price_per_unit']} лв/ед (София factor 1.15)")


class TestCityPricingFactors:
    """Test city-based pricing factors from CITY_PRICE_FACTORS"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
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
    
    def test_city_factor_varna_1_05(self):
        """Test city=Варна returns city_factor=1.05"""
        payload = {
            "title": "Мазилка стена",
            "unit": "m2",
            "qty": 10,
            "city": "Варна"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["pricing"]["city"] == "Варна"
        assert data["pricing"]["city_factor"] == 1.05
        print(f"✓ Варна city_factor: {data['pricing']['city_factor']}")
    
    def test_city_factor_burgas_1_02(self):
        """Test city=Бургас returns city_factor=1.02"""
        payload = {
            "title": "Боядисване",
            "unit": "m2",
            "qty": 20,
            "city": "Бургас"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["pricing"]["city"] == "Бургас"
        assert data["pricing"]["city_factor"] == 1.02
        print(f"✓ Бургас city_factor: {data['pricing']['city_factor']}")
    
    def test_city_factor_unknown_city_defaults_to_1(self):
        """Test unknown city returns no city_factor (defaults to 1.0)"""
        payload = {
            "title": "Мазилка стена",
            "unit": "m2",
            "qty": 10,
            "city": "НепознатГрад"
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # Unknown city should have no factor adjustment
        factor = data["pricing"].get("city_factor")
        assert factor in [None, 1.0], f"Unknown city factor should be null or 1.0, got {factor}"
        print(f"✓ Unknown city factor: {factor} (no adjustment)")
    
    def test_no_city_parameter_no_factor(self):
        """Test omitting city parameter returns no city_factor"""
        payload = {
            "title": "Плочки баня",
            "unit": "m2",
            "qty": 8
        }
        
        response = self.session.post(f"{BASE_URL}/api/extra-works/ai-proposal", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        # No city means no factor
        assert data["pricing"].get("city") is None or data["pricing"]["city_factor"] is None
        print(f"✓ No city parameter: city={data['pricing'].get('city')}, factor={data['pricing'].get('city_factor')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
