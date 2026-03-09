"""
Test Two-Stage AI for Extra Works - P1/P2 Feature
Stage A: POST /api/extra-works/ai-fast (rule-based, instant)
Stage B: POST /api/extra-works/ai-refine (LLM hybrid, async)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"


class TestTwoStageAI:
    """Test Two-Stage AI endpoints for Extra Works"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("token")
        assert token, "No token in login response"
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
    # ========= Stage A: Fast (Rule-Based) Endpoint Tests =========
    
    def test_ai_fast_single_line(self):
        """POST /api/extra-works/ai-fast with single line returns stage='fast'"""
        payload = {
            "lines": [{"title": "Полагане на плочки", "unit": "m2", "qty": 10}],
            "city": "София"
        }
        
        start = time.time()
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        elapsed = time.time() - start
        
        assert resp.status_code == 200, f"ai-fast failed: {resp.text}"
        data = resp.json()
        
        # Verify stage='fast'
        assert data.get("stage") == "fast", f"Expected stage='fast', got: {data.get('stage')}"
        
        # Verify response structure
        assert "results" in data, "Missing 'results' key"
        assert "combined_materials" in data, "Missing 'combined_materials' key"
        assert "grand_total" in data, "Missing 'grand_total' key"
        assert "line_count" in data, "Missing 'line_count' key"
        assert data["line_count"] == 1, f"Expected line_count=1, got {data['line_count']}"
        
        # Verify per-line stage
        result = data["results"][0]
        assert result.get("stage") == "fast", f"Per-line stage should be 'fast', got: {result.get('stage')}"
        
        # Verify hourly_info with worker_type
        assert "hourly_info" in result, "Missing 'hourly_info' in result"
        assert "worker_type" in result["hourly_info"], "Missing 'worker_type' in hourly_info"
        
        print(f"✓ ai-fast single line passed in {elapsed:.2f}s")
        print(f"  Worker type: {result['hourly_info']['worker_type']}, Provider: {result.get('provider')}")
        
    def test_ai_fast_batch_multiple_lines(self):
        """POST /api/extra-works/ai-fast with multiple lines processes all lines"""
        payload = {
            "lines": [
                {"title": "Мазилка гипсова", "unit": "m2", "qty": 15},
                {"title": "Боядисване с латекс", "unit": "m2", "qty": 20},
                {"title": "Шпакловка финишна", "unit": "m2", "qty": 12}
            ],
            "city": "Пловдив"
        }
        
        start = time.time()
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        elapsed = time.time() - start
        
        assert resp.status_code == 200, f"ai-fast batch failed: {resp.text}"
        data = resp.json()
        
        # All results should have stage='fast'
        assert data["stage"] == "fast"
        assert data["line_count"] == 3, f"Expected 3 lines, got {data['line_count']}"
        
        for i, result in enumerate(data["results"]):
            assert result.get("stage") == "fast", f"Line {i} stage not 'fast'"
            assert "hourly_info" in result, f"Line {i} missing hourly_info"
            assert "worker_type" in result["hourly_info"], f"Line {i} missing worker_type"
            print(f"  Line {i+1}: {result['_input']['title'][:30]} - {result['hourly_info']['worker_type']}")
        
        print(f"✓ ai-fast batch (3 lines) passed in {elapsed:.2f}s")
        
    def test_ai_fast_is_instant(self):
        """ai-fast should complete in <1 second (rule-based, no LLM call)"""
        payload = {
            "lines": [
                {"title": "Гипсокартон монтаж", "unit": "m2", "qty": 8},
                {"title": "Електро точка", "unit": "pcs", "qty": 5}
            ],
            "city": "София"
        }
        
        start = time.time()
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        elapsed = time.time() - start
        
        assert resp.status_code == 200
        
        # Fast endpoint should be < 1 second
        assert elapsed < 1.0, f"ai-fast took {elapsed:.2f}s, expected <1s"
        print(f"✓ ai-fast completed in {elapsed:.3f}s (under 1s threshold)")
        
    def test_ai_fast_has_hourly_info_with_worker_type(self):
        """ai-fast response includes hourly_info with worker_type for all lines"""
        payload = {
            "lines": [
                {"title": "ВиК инсталация", "unit": "pcs", "qty": 3},
                {"title": "Плочки теракот", "unit": "m2", "qty": 6}
            ],
            "city": "Варна"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        for i, result in enumerate(data["results"]):
            hi = result.get("hourly_info")
            assert hi is not None, f"Line {i} missing hourly_info"
            assert "worker_type" in hi, f"Line {i} missing worker_type"
            assert "hourly_rate" in hi, f"Line {i} missing hourly_rate"
            assert "min_job_price" in hi, f"Line {i} missing min_job_price"
            print(f"  Line {i+1}: {hi['worker_type']} @ {hi['hourly_rate']}лв/ч, min={hi['min_job_price']}лв")
        
        print(f"✓ ai-fast hourly_info with worker_type verified")
        
    # ========= Stage B: Refine (LLM) Endpoint Tests =========
    
    def test_ai_refine_single_line(self):
        """POST /api/extra-works/ai-refine with single line returns stage='refined'"""
        payload = {
            "lines": [{"title": "Полагане на мазилка", "unit": "m2", "qty": 5}],
            "city": "София"
        }
        
        start = time.time()
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-refine", json=payload, timeout=60)
        elapsed = time.time() - start
        
        assert resp.status_code == 200, f"ai-refine failed: {resp.text}"
        data = resp.json()
        
        # Verify stage='refined'
        assert data.get("stage") == "refined", f"Expected stage='refined', got: {data.get('stage')}"
        
        # Verify per-line stage
        result = data["results"][0]
        assert result.get("stage") == "refined", f"Per-line stage should be 'refined', got: {result.get('stage')}"
        
        # Verify hourly_info with worker_type
        assert "hourly_info" in result, "Missing 'hourly_info' in refined result"
        assert "worker_type" in result["hourly_info"], "Missing 'worker_type' in hourly_info"
        
        print(f"✓ ai-refine single line passed in {elapsed:.2f}s")
        print(f"  Provider: {result.get('provider')}, Confidence: {result.get('confidence')}")
        
    def test_ai_refine_batch_multiple_lines(self):
        """POST /api/extra-works/ai-refine with batch processes all with LLM"""
        payload = {
            "lines": [
                {"title": "Боядисване стени", "unit": "m2", "qty": 10},
                {"title": "Монтаж контакти", "unit": "pcs", "qty": 4}
            ],
            "city": "Бургас"
        }
        
        start = time.time()
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-refine", json=payload, timeout=90)
        elapsed = time.time() - start
        
        assert resp.status_code == 200, f"ai-refine batch failed: {resp.text}"
        data = resp.json()
        
        assert data["stage"] == "refined"
        assert data["line_count"] == 2
        
        for i, result in enumerate(data["results"]):
            assert result.get("stage") == "refined", f"Line {i} stage not 'refined'"
            assert "hourly_info" in result, f"Line {i} missing hourly_info"
            print(f"  Line {i+1}: Provider={result.get('provider')}, Conf={result.get('confidence')}")
        
        print(f"✓ ai-refine batch (2 lines) passed in {elapsed:.2f}s")
        
    def test_ai_refine_is_slower_than_fast(self):
        """ai-refine should take significantly longer than ai-fast (LLM call)"""
        payload = {
            "lines": [{"title": "Шпакловка тавани", "unit": "m2", "qty": 8}],
            "city": "София"
        }
        
        # Time ai-fast
        start = time.time()
        fast_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        fast_elapsed = time.time() - start
        assert fast_resp.status_code == 200
        
        # Time ai-refine
        start = time.time()
        refine_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-refine", json=payload, timeout=60)
        refine_elapsed = time.time() - start
        assert refine_resp.status_code == 200
        
        # Refine should be at least 2x slower (typically 10-20x)
        assert refine_elapsed > fast_elapsed * 2, \
            f"Expected refine to be significantly slower. Fast: {fast_elapsed:.2f}s, Refine: {refine_elapsed:.2f}s"
        
        print(f"✓ Timing verified: ai-fast={fast_elapsed:.3f}s, ai-refine={refine_elapsed:.2f}s")
        print(f"  Refine is {refine_elapsed/fast_elapsed:.1f}x slower (expected due to LLM)")
        
    def test_ai_refine_has_hourly_info_with_worker_type(self):
        """ai-refine response includes hourly_info with worker_type"""
        payload = {
            "lines": [{"title": "Електрическа инсталация", "unit": "pcs", "qty": 6}],
            "city": "Русе"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-refine", json=payload, timeout=60)
        assert resp.status_code == 200
        data = resp.json()
        
        result = data["results"][0]
        hi = result.get("hourly_info")
        assert hi is not None, "Missing hourly_info"
        assert "worker_type" in hi, "Missing worker_type"
        assert "hourly_rate" in hi, "Missing hourly_rate"
        
        print(f"✓ ai-refine hourly_info verified: {hi['worker_type']} @ {hi['hourly_rate']}лв/ч")
        
    # ========= Cross-Endpoint Comparison Tests =========
    
    def test_both_endpoints_return_correct_structure(self):
        """Both endpoints return same structure with different stage values"""
        payload = {
            "lines": [{"title": "Гипсова мазилка стени", "unit": "m2", "qty": 12}],
            "city": "София"
        }
        
        fast_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        refine_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-refine", json=payload, timeout=60)
        
        assert fast_resp.status_code == 200
        assert refine_resp.status_code == 200
        
        fast_data = fast_resp.json()
        refine_data = refine_resp.json()
        
        # Both should have same keys
        expected_keys = {"results", "combined_materials", "grand_total", "line_count", "stage"}
        assert set(fast_data.keys()) == expected_keys, f"Fast keys: {fast_data.keys()}"
        assert set(refine_data.keys()) == expected_keys, f"Refine keys: {refine_data.keys()}"
        
        # Stage should differ
        assert fast_data["stage"] == "fast"
        assert refine_data["stage"] == "refined"
        
        # Per-line stages should match
        assert fast_data["results"][0]["stage"] == "fast"
        assert refine_data["results"][0]["stage"] == "refined"
        
        print(f"✓ Both endpoints return correct structure with distinct stages")
        
    def test_batch_with_location_info(self):
        """Both endpoints handle location info correctly"""
        payload = {
            "lines": [{
                "title": "Полагане плочки баня",
                "unit": "m2",
                "qty": 15,
                "location_floor": "2",
                "location_room": "Баня",
                "location_zone": "Стени"
            }],
            "city": "София"
        }
        
        fast_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert fast_resp.status_code == 200
        
        data = fast_resp.json()
        result = data["results"][0]
        
        # Verify location info is passed through
        assert result["_input"]["location_floor"] == "2"
        assert result["_input"]["location_room"] == "Баня"
        assert result["_input"]["location_zone"] == "Стени"
        
        print(f"✓ Location info preserved in batch response")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
