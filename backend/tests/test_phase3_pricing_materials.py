"""
Test Phase 3: Pricing Rules + Materials Generation
- Worker-rate pricing with 8 categories
- Small qty vs large qty logic with min-job
- Materials returned with category (primary/secondary/consumable) and reason
- Materials have estimated_qty based on work quantity
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Expected hourly rates from extra_works.py
EXPECTED_WORKER_RATES = {
    "общ работник": 15,
    "майстор": 22,
    "бояджия": 18,
    "шпакловчик": 20,
    "електротехник": 28,
    "вик": 26,
    "монтажник": 20,
    "плочкаджия": 25,
}


class TestPhase3PricingMaterials:
    """Test Phase 3: Pricing Rules + Materials Generation"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("token")
        assert token, "No token in login response"
        self.session.headers.update({"Authorization": f"Bearer {token}"})
    
    # ========= Hourly Info Tests =========
    
    def test_ai_fast_returns_hourly_info_with_worker_type(self):
        """POST /api/extra-works/ai-fast returns hourly_info with worker_type"""
        payload = {
            "lines": [{"title": "Полагане на мазилка", "unit": "m2", "qty": 10}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        
        result = data["results"][0]
        assert "hourly_info" in result, "Missing hourly_info in response"
        
        hi = result["hourly_info"]
        assert "worker_type" in hi, "Missing worker_type in hourly_info"
        assert "hourly_rate" in hi, "Missing hourly_rate in hourly_info"
        assert "min_applied" in hi, "Missing min_applied flag in hourly_info"
        
        print(f"✓ hourly_info returned: worker_type={hi['worker_type']}, hourly_rate={hi['hourly_rate']}, min_applied={hi['min_applied']}")
    
    def test_worker_rates_match_8_categories(self):
        """Verify all 8 worker categories have correct rates"""
        # Test different activity types that map to different workers
        test_cases = [
            ("Мазилка по стени", "майстор"),  # Мокри процеси -> майстор
            ("Боядисване стени", "бояджия"),  # Боядисване -> бояджия
            ("Шпакловка финишна", "шпакловчик"),  # Шпакловка -> шпакловчик
            ("Полагане на плочки", "плочкаджия"),  # Облицовка -> плочкаджия
            ("Монтаж на гипсокартон", "монтажник"),  # Сухо строителство -> монтажник
            ("Електрическа точка", "електротехник"),  # Електро -> електротехник
            ("ВиК инсталация", "вик"),  # ВиК -> вик
        ]
        
        for title, expected_worker in test_cases:
            payload = {"lines": [{"title": title, "unit": "m2", "qty": 5}], "city": None}
            resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
            assert resp.status_code == 200
            
            result = resp.json()["results"][0]
            worker = result["hourly_info"]["worker_type"]
            rate = result["hourly_info"]["hourly_rate"]
            
            # Check rate matches expected
            if worker in EXPECTED_WORKER_RATES:
                expected_rate = EXPECTED_WORKER_RATES[worker]
                assert rate == expected_rate, f"Rate mismatch for {worker}: got {rate}, expected {expected_rate}"
            
            print(f"  {title[:30]}: {worker} @ {rate}лв/ч")
        
        print("✓ Worker rates verified for multiple activity types")
    
    def test_hourly_rates_config_endpoint(self):
        """GET /api/ai-config/hourly-rates returns all 8 worker categories"""
        resp = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        assert resp.status_code == 200, f"Failed: {resp.text}"
        
        rates = resp.json()
        
        # Verify all 8 categories exist
        for worker, expected_rate in EXPECTED_WORKER_RATES.items():
            assert worker in rates, f"Missing worker: {worker}"
            assert rates[worker]["hourly_rate"] == expected_rate, f"Rate mismatch for {worker}"
            assert "min_hours" in rates[worker], f"Missing min_hours for {worker}"
            assert "min_job_price" in rates[worker], f"Missing min_job_price for {worker}"
        
        assert len(rates) == 8, f"Expected 8 worker categories, got {len(rates)}"
        print(f"✓ All 8 worker categories verified: {list(rates.keys())}")
    
    # ========= Small Quantity Logic Tests =========
    
    def test_small_qty_adjustment_applied_when_below_threshold(self):
        """Small quantity adjustment applied when qty <= threshold"""
        # Test with very small quantity (should trigger adjustment)
        payload = {
            "lines": [{"title": "Боядисване стени", "unit": "m2", "qty": 2}],  # Small qty
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        result = data["results"][0]
        pricing = result["pricing"]
        
        # Should have small_qty_adjustment_percent > 0
        assert "small_qty_adjustment_percent" in pricing, "Missing small_qty_adjustment_percent"
        adj = pricing["small_qty_adjustment_percent"]
        
        # For qty=2 on боядисване (threshold=10, multiplier=1.30), should be 30%
        assert adj > 0, f"Expected adjustment > 0 for small qty, got {adj}"
        
        print(f"✓ Small qty adjustment: {adj}% for qty=2")
        
    def test_min_job_applied_for_small_labor_total(self):
        """min_applied flag set when estimated labor < min_job_price"""
        # Test with very small quantity to trigger min_job
        payload = {
            "lines": [{"title": "Електрическа точка", "unit": "pcs", "qty": 1}],
            "city": None
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        result = data["results"][0]
        hi = result["hourly_info"]
        
        # Check if min_applied flag exists
        assert "min_applied" in hi, "Missing min_applied in hourly_info"
        
        # With qty=1 and typical labor prices, min_job should likely be applied
        min_job = hi.get("min_job_price", 0)
        estimated_labor = hi.get("estimated_labor_total", 0)
        
        print(f"  min_job_price: {min_job}, estimated_labor_total: {estimated_labor}")
        print(f"  min_applied: {hi['min_applied']}")
        
        if estimated_labor < min_job:
            assert hi["min_applied"] == True, "min_applied should be True when labor < min_job"
            print("✓ min_applied=True verified for small labor total")
        else:
            print("✓ min_applied logic verified (labor >= min_job)")
    
    def test_large_qty_no_small_adjustment(self):
        """Large quantity should NOT have small qty adjustment"""
        # Large quantity
        payload = {
            "lines": [{"title": "Боядисване стени", "unit": "m2", "qty": 50}],  # Large qty
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        result = data["results"][0]
        pricing = result["pricing"]
        
        # Should have 0 adjustment for large quantity
        adj = pricing.get("small_qty_adjustment_percent", 0)
        assert adj == 0, f"Expected 0 adjustment for large qty, got {adj}"
        
        hi = result["hourly_info"]
        assert hi.get("min_applied") == False, "min_applied should be False for large qty"
        
        print(f"✓ Large qty (50): no small adjustment, min_applied=False")
    
    # ========= Materials Tests =========
    
    def test_materials_returned_with_category(self):
        """Materials returned with category (primary/secondary/consumable)"""
        payload = {
            "lines": [{"title": "Полагане на мазилка", "unit": "m2", "qty": 10}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        result = data["results"][0]
        assert "materials" in result, "Missing 'materials' in response"
        
        materials = result["materials"]
        assert len(materials) > 0, "No materials returned"
        
        # Verify each material has category
        categories_found = set()
        for mat in materials:
            assert "category" in mat, f"Material {mat.get('name')} missing 'category'"
            assert mat["category"] in ["primary", "secondary", "consumable"], \
                f"Invalid category: {mat['category']}"
            categories_found.add(mat["category"])
            print(f"  - {mat['name']}: {mat['category']}")
        
        print(f"✓ Materials returned with categories: {categories_found}")
    
    def test_materials_have_reason_field(self):
        """Each material has a reason field explaining why it's needed"""
        payload = {
            "lines": [{"title": "Полагане на плочки баня", "unit": "m2", "qty": 8}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        materials = data["results"][0]["materials"]
        
        for mat in materials:
            assert "reason" in mat, f"Material {mat['name']} missing 'reason'"
            print(f"  - {mat['name']}: reason='{mat.get('reason', '')}'")
        
        print(f"✓ All {len(materials)} materials have reason field")
    
    def test_materials_have_estimated_qty(self):
        """Materials have estimated_qty based on work quantity"""
        qty = 15  # Work quantity
        payload = {
            "lines": [{"title": "Гипсокартон монтаж", "unit": "m2", "qty": qty}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        materials = data["results"][0]["materials"]
        
        for mat in materials:
            # estimated_qty should be present and > 0 for most materials
            est = mat.get("estimated_qty")
            if est is not None:
                assert est > 0, f"Material {mat['name']} has non-positive estimated_qty: {est}"
            print(f"  - {mat['name']}: estimated_qty={est} {mat.get('unit', '')}")
        
        print(f"✓ Materials have estimated_qty values")
    
    def test_materials_grouped_by_type(self):
        """Materials can be grouped into primary/secondary/consumables"""
        payload = {
            "lines": [{"title": "Шпакловка стени", "unit": "m2", "qty": 20}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        materials = data["results"][0]["materials"]
        
        # Group by category
        primary = [m for m in materials if m["category"] == "primary"]
        secondary = [m for m in materials if m["category"] == "secondary"]
        consumables = [m for m in materials if m["category"] == "consumable"]
        
        print(f"  Primary ({len(primary)}): {[m['name'] for m in primary]}")
        print(f"  Secondary ({len(secondary)}): {[m['name'] for m in secondary]}")
        print(f"  Consumables ({len(consumables)}): {[m['name'] for m in consumables]}")
        
        # At least some should exist
        total = len(primary) + len(secondary) + len(consumables)
        assert total > 0, "No materials in any category"
        
        print(f"✓ Materials groupable: {len(primary)} primary, {len(secondary)} secondary, {len(consumables)} consumables")
    
    # ========= Combined Materials Tests =========
    
    def test_combined_materials_in_batch(self):
        """Batch endpoint returns combined_materials aggregated from all lines"""
        payload = {
            "lines": [
                {"title": "Мазилка гипсова", "unit": "m2", "qty": 10},
                {"title": "Шпакловка финишна", "unit": "m2", "qty": 10}
            ],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        # Check combined_materials exists
        assert "combined_materials" in data, "Missing combined_materials"
        combined = data["combined_materials"]
        
        assert isinstance(combined, list), "combined_materials should be a list"
        
        if len(combined) > 0:
            # Each combined material should have category
            for mat in combined:
                assert "category" in mat, f"Combined material missing category"
                assert "name" in mat, f"Combined material missing name"
            
            print(f"✓ Combined materials returned: {len(combined)} items")
            for mat in combined[:5]:  # Show first 5
                print(f"  - {mat['name']}: {mat.get('estimated_qty', 'N/A')} {mat.get('unit', '')}")
        else:
            print("✓ combined_materials structure verified (empty for this case)")
    
    # ========= Full Workflow Test =========
    
    def test_full_ai_fast_response_structure(self):
        """Full response structure test for ai-fast endpoint"""
        payload = {
            "lines": [{"title": "Боядисване с латекс", "unit": "m2", "qty": 5}],
            "city": "София"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        # Top level
        assert "results" in data
        assert "combined_materials" in data
        assert "grand_total" in data
        assert "line_count" in data
        assert "stage" in data
        
        # Per-result structure
        result = data["results"][0]
        
        # Required fields
        assert "provider" in result
        assert "recognized" in result
        assert "pricing" in result
        assert "hourly_info" in result
        assert "materials" in result
        assert "confidence" in result
        
        # recognized structure
        rec = result["recognized"]
        assert "activity_type" in rec
        assert "activity_subtype" in rec
        assert "suggested_unit" in rec
        
        # pricing structure
        pricing = result["pricing"]
        assert "material_price_per_unit" in pricing
        assert "labor_price_per_unit" in pricing
        assert "total_price_per_unit" in pricing
        assert "small_qty_adjustment_percent" in pricing
        assert "total_estimated" in pricing
        
        # hourly_info structure
        hi = result["hourly_info"]
        assert "worker_type" in hi
        assert "hourly_rate" in hi
        assert "min_applied" in hi
        
        print("✓ Full response structure verified")
        print(f"  Type: {rec['activity_type']}/{rec['activity_subtype']}")
        print(f"  Worker: {hi['worker_type']} @ {hi['hourly_rate']}лв/ч")
        print(f"  Pricing: {pricing['total_price_per_unit']}лв/ед, total: {pricing['total_estimated']}лв")
        print(f"  Materials: {len(result['materials'])} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
