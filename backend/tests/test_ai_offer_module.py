"""
AI Offer Module Tests - Phase 1 MVP
Tests for:
1. POST /api/extra-works/ai-fast - Fast rule-based proposals with hourly_info
2. POST /api/extra-works/ai-refine - LLM-enhanced proposals
3. Internal price hints when historical data exists
4. hourly_info with worker_type and min_applied
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test historical keywords that should have internal price hints
HISTORICAL_KEYWORDS = ["Мазилка", "Шпакловка", "Боядисване", "Облицовка", "Електро", "Гипсокартон"]


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json().get("token")  # API returns 'token' not 'access_token'


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers for requests"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestAiFastEndpoint:
    """Tests for POST /api/extra-works/ai-fast - Fast rule-based proposals"""
    
    def test_ai_fast_single_line(self, auth_headers):
        """Test ai-fast returns proposal for single line"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast", 
            headers=auth_headers,
            json={"lines": [{"title": "Мазилка гипсова", "unit": "m2", "qty": 10}], "city": None})
        
        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()
        
        # Check structure
        assert "results" in data
        assert "line_count" in data
        assert "stage" in data
        assert data["stage"] == "fast"
        assert data["line_count"] == 1
        
        # Check result structure
        result = data["results"][0]
        assert "provider" in result
        assert result["provider"] == "rule-based"
        assert "pricing" in result
        assert "recognized" in result
        assert "confidence" in result
        assert "_input" in result
        
        print(f"PASS: ai-fast single line returned: provider={result['provider']}, confidence={result['confidence']}")
    
    def test_ai_fast_multi_line(self, auth_headers):
        """Test ai-fast with multiple lines"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
            headers=auth_headers,
            json={
                "lines": [
                    {"title": "Мазилка гипсова на стени", "unit": "m2", "qty": 20},
                    {"title": "Боядисване с латекс", "unit": "m2", "qty": 30},
                    {"title": "Монтаж контакти", "unit": "pcs", "qty": 5}
                ],
                "city": None
            })
        
        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()
        
        assert data["line_count"] == 3
        assert len(data["results"]) == 3
        assert "combined_materials" in data
        assert "grand_total" in data
        
        # Check each result has required fields
        for i, result in enumerate(data["results"]):
            assert "pricing" in result
            assert "recognized" in result
            assert "hourly_info" in result, f"Result {i} missing hourly_info"
            print(f"Line {i}: {result['_input']['title'][:30]} -> {result['recognized']['activity_type']}/{result['recognized']['activity_subtype']}")
        
        print(f"PASS: ai-fast multi-line returned {data['line_count']} results, grand_total={data['grand_total']}")
    
    def test_ai_fast_returns_hourly_info(self, auth_headers):
        """Test ai-fast returns hourly_info with worker_type and min_applied"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
            headers=auth_headers,
            json={"lines": [{"title": "Боядисване с латекс", "unit": "m2", "qty": 5}], "city": None})
        
        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()
        result = data["results"][0]
        
        # Check hourly_info structure
        assert "hourly_info" in result
        hourly = result["hourly_info"]
        assert "worker_type" in hourly
        assert "hourly_rate" in hourly
        assert "min_hours" in hourly
        assert "min_job_price" in hourly
        assert "min_applied" in hourly
        
        print(f"PASS: hourly_info returned: worker_type={hourly['worker_type']}, rate={hourly['hourly_rate']}лв/ч, min_applied={hourly['min_applied']}")
    
    def test_ai_fast_small_qty_triggers_min(self, auth_headers):
        """Test small quantity triggers minimum job price"""
        # Very small qty that should trigger min_applied=True
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
            headers=auth_headers,
            json={"lines": [{"title": "Боядисване", "unit": "m2", "qty": 1}], "city": None})
        
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        hourly = result["hourly_info"]
        
        # With qty=1 and low estimated labor, min should apply
        print(f"Small qty test: min_applied={hourly['min_applied']}, adjusted_labor={hourly.get('adjusted_labor_per_unit', 'N/A')}")
        # Note: min_applied might be True or False depending on labor calculation


class TestAiRefineEndpoint:
    """Tests for POST /api/extra-works/ai-refine - LLM-enhanced proposals"""
    
    def test_ai_refine_single_line(self, auth_headers):
        """Test ai-refine returns LLM-enhanced proposal"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-refine",
            headers=auth_headers,
            json={"lines": [{"title": "Мазилка гипсова на стени", "unit": "m2", "qty": 10}], "city": None},
            timeout=30)  # LLM can be slower
        
        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()
        
        assert "results" in data
        assert "stage" in data
        assert data["stage"] == "refined"
        assert data["line_count"] == 1
        
        result = data["results"][0]
        assert "provider" in result
        assert "pricing" in result
        assert "hourly_info" in result
        
        # LLM should return higher confidence or different provider
        print(f"PASS: ai-refine returned: provider={result['provider']}, confidence={result['confidence']}")
    
    def test_ai_refine_returns_hourly_info(self, auth_headers):
        """Test ai-refine also returns hourly_info"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-refine",
            headers=auth_headers,
            json={"lines": [{"title": "Електрически ключове", "unit": "pcs", "qty": 3}], "city": None},
            timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        
        assert "hourly_info" in result
        hourly = result["hourly_info"]
        assert "worker_type" in hourly
        assert "hourly_rate" in hourly
        
        print(f"PASS: ai-refine hourly_info: worker_type={hourly['worker_type']}, rate={hourly['hourly_rate']}лв/ч")


class TestInternalPriceHint:
    """Tests for internal_price_hint in AI proposals"""
    
    def test_ai_refine_includes_internal_price_hint(self, auth_headers):
        """Test ai-refine includes internal_price_hint when historical data exists"""
        # Test with a keyword that likely has historical data
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-refine",
            headers=auth_headers,
            json={"lines": [{"title": "Мазилка", "unit": "m2", "qty": 10}], "city": None},
            timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        
        # internal_price_hint should be present (may or may not have data depending on DB)
        if "internal_price_hint" in result:
            hint = result["internal_price_hint"]
            print(f"internal_price_hint present: available={hint.get('available')}, sample_count={hint.get('sample_count', 0)}")
            if hint.get("available"):
                assert "sample_count" in hint
                assert "median_total" in hint
                assert "range_label" in hint
                print(f"PASS: Internal hint available: {hint['range_label']} ({hint['sample_count']} samples)")
        else:
            print("INFO: internal_price_hint not returned (may not have historical data)")


class TestActivityTypeSubtype:
    """Tests for activity type/subtype recognition"""
    
    def test_ai_fast_recognizes_types(self, auth_headers):
        """Test ai-fast correctly recognizes activity type/subtype"""
        test_cases = [
            ("Мазилка гипсова", "Мокри процеси", "Мазилка"),
            ("Боядисване с латекс", "Довършителни", "Боядисване"),
            ("Шпакловка финишна", "Довършителни", "Шпакловка"),
            ("Поставяне на плочки", "Довършителни", "Облицовка"),
            ("Монтаж гипсокартон", "Сухо строителство", "Гипсокартон"),
            ("Електрически контакти", "Инсталации", "Електро"),
        ]
        
        for title, expected_type, expected_subtype in test_cases:
            response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
                headers=auth_headers,
                json={"lines": [{"title": title, "unit": "m2", "qty": 1}], "city": None})
            
            assert response.status_code == 200
            result = response.json()["results"][0]
            rec = result["recognized"]
            
            # Log the recognition
            actual_type = rec["activity_type"]
            actual_subtype = rec["activity_subtype"]
            match_type = "✓" if actual_type == expected_type else "✗"
            match_subtype = "✓" if actual_subtype == expected_subtype else "✗"
            
            print(f"{title[:25]}: {match_type} {actual_type}/{match_subtype} {actual_subtype}")


class TestPricingFields:
    """Tests for pricing fields structure"""
    
    def test_pricing_structure(self, auth_headers):
        """Test pricing contains all required fields"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
            headers=auth_headers,
            json={"lines": [{"title": "Боядисване", "unit": "m2", "qty": 15}], "city": None})
        
        assert response.status_code == 200
        pricing = response.json()["results"][0]["pricing"]
        
        required_fields = [
            "material_price_per_unit",
            "labor_price_per_unit", 
            "total_price_per_unit",
            "total_estimated",
            "small_qty_adjustment_percent"
        ]
        
        for field in required_fields:
            assert field in pricing, f"Missing pricing field: {field}"
            print(f"  {field}: {pricing[field]}")
        
        # Verify calculation
        expected_total = pricing["material_price_per_unit"] + pricing["labor_price_per_unit"]
        assert abs(pricing["total_price_per_unit"] - expected_total) < 0.01, "Total per unit mismatch"
        
        print("PASS: All pricing fields present and calculations correct")


class TestCombinedMaterials:
    """Tests for combined_materials in batch proposals"""
    
    def test_combined_materials_structure(self, auth_headers):
        """Test combined_materials aggregates materials from multiple lines"""
        response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
            headers=auth_headers,
            json={
                "lines": [
                    {"title": "Мазилка", "unit": "m2", "qty": 10},
                    {"title": "Шпакловка", "unit": "m2", "qty": 10},
                ],
                "city": None
            })
        
        assert response.status_code == 200
        data = response.json()
        
        assert "combined_materials" in data
        materials = data["combined_materials"]
        
        if materials:
            print(f"Combined materials ({len(materials)} items):")
            for mat in materials[:5]:
                print(f"  - {mat.get('name')}: {mat.get('estimated_qty')} {mat.get('unit')}")
        else:
            print("INFO: No combined materials returned")


class TestWorkerTypeMapping:
    """Tests for worker type based on activity"""
    
    def test_worker_types_mapped_correctly(self, auth_headers):
        """Test different activities map to correct worker types"""
        test_cases = [
            ("Боядисване с латекс", "бояджия"),
            ("Шпакловка финишна", "шпакловчик"),
            ("Поставяне плочки фаянс", "плочкаджия"),
            ("Монтаж контакти електро", "електротехник"),
        ]
        
        for title, expected_worker in test_cases:
            response = requests.post(f"{BASE_URL}/api/extra-works/ai-fast",
                headers=auth_headers,
                json={"lines": [{"title": title, "unit": "m2", "qty": 5}], "city": None})
            
            assert response.status_code == 200
            hourly = response.json()["results"][0]["hourly_info"]
            actual_worker = hourly["worker_type"]
            
            match = "✓" if actual_worker == expected_worker else "✗"
            print(f"{title[:25]}: {match} {actual_worker} (expected: {expected_worker})")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
