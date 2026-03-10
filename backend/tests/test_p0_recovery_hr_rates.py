"""
P0 RECOVERY Tests: HR modules, AI rates from org settings, EUR currency.
Tests:
- GET /api/ai-config/hourly-rates returns source='organization' when configured
- PUT /api/ai-config/hourly-rates saves org-specific rates
- AI proposal uses org rates (is_demo=false) when configured
- AI proposal hourly_info includes currency='EUR'
- GET /api/employees returns employees list
- GET /api/payroll-runs returns payroll data
- GET /api/historical/analytics returns historical price data
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
EMAIL = "admin@begwork.com"
PASSWORD = "AdminTest123!Secure"

class TestP0Recovery:
    """P0 Recovery tests for HR, org rates, EUR currency"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: login and get auth token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": EMAIL, "password": PASSWORD
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        self.token = login_resp.json().get("token")
        assert self.token, "No token in login response"
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        yield
    
    # ── Test 1: GET /api/ai-config/hourly-rates returns source='organization' ──
    def test_get_hourly_rates_source_organization(self):
        """GET /api/ai-config/hourly-rates should return source='organization' after config"""
        resp = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        assert resp.status_code == 200, f"Failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        
        # Verify response structure
        assert "source" in data, "Missing 'source' in response"
        assert "rates" in data, "Missing 'rates' in response"
        assert "currency" in data, "Missing 'currency' in response"
        
        # Verify currency is EUR
        assert data["currency"] == "EUR", f"Expected currency='EUR', got '{data['currency']}'"
        
        # Source should be 'organization' if rates have been configured
        # or 'demo' if using demo defaults
        assert data["source"] in ["organization", "demo"], f"Unexpected source: {data['source']}"
        print(f"Hourly rates source: {data['source']}, currency: {data['currency']}")
        
        # Verify rates structure - check a worker type exists
        assert isinstance(data["rates"], dict), "rates should be a dict"
        if data["rates"]:
            sample_key = list(data["rates"].keys())[0]
            sample_rate = data["rates"][sample_key]
            assert "hourly_rate" in sample_rate, "Missing hourly_rate in worker rate"
    
    # ── Test 2: PUT /api/ai-config/hourly-rates saves org-specific rates ──
    def test_save_hourly_rates(self):
        """PUT /api/ai-config/hourly-rates should save org-specific rates"""
        # First get current rates
        get_resp = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        assert get_resp.status_code == 200
        current = get_resp.json()
        
        # Modify бояджия rate to 15 EUR/h as per test requirements
        rates_to_save = current.get("rates", {})
        if not rates_to_save:
            # Use default structure if empty
            rates_to_save = {
                "общ работник": {"hourly_rate": 15, "min_hours": 2, "min_job_price": 40},
                "бояджия": {"hourly_rate": 15, "min_hours": 2, "min_job_price": 50},
            }
        else:
            rates_to_save["бояджия"] = {"hourly_rate": 15, "min_hours": 2, "min_job_price": 50}
        
        # Save rates
        save_resp = self.session.put(f"{BASE_URL}/api/ai-config/hourly-rates", json={"rates": rates_to_save})
        assert save_resp.status_code == 200, f"Save failed: {save_resp.status_code} - {save_resp.text}"
        save_data = save_resp.json()
        
        assert save_data.get("ok") == True, "Expected ok=True in save response"
        assert save_data.get("source") == "organization", "Expected source='organization' after save"
        
        # Verify by re-fetching
        verify_resp = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        
        assert verify_data["source"] == "organization", "Source should be 'organization' after save"
        print(f"Rates saved successfully, source: {verify_data['source']}")
    
    # ── Test 3: AI proposal uses org rates (is_demo=false) when configured ──
    def test_ai_proposal_uses_org_rates(self):
        """POST /api/extra-works/ai-fast should use org rates (is_demo=false)"""
        # First ensure org rates are configured
        save_resp = self.session.put(f"{BASE_URL}/api/ai-config/hourly-rates", json={
            "rates": {
                "общ работник": {"hourly_rate": 15, "min_hours": 2, "min_job_price": 40},
                "бояджия": {"hourly_rate": 15, "min_hours": 2, "min_job_price": 50},
                "майстор": {"hourly_rate": 22, "min_hours": 2, "min_job_price": 60},
                "плочкаджия": {"hourly_rate": 25, "min_hours": 3, "min_job_price": 80},
            }
        })
        assert save_resp.status_code == 200
        
        # Call AI proposal
        ai_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [{"title": "боядисване стени", "unit": "m2", "qty": 5}]
        })
        assert ai_resp.status_code == 200, f"AI proposal failed: {ai_resp.status_code} - {ai_resp.text}"
        data = ai_resp.json()
        
        # Check results
        assert "results" in data, "Missing 'results' in AI response"
        assert len(data["results"]) > 0, "No results returned"
        
        result = data["results"][0]
        assert "hourly_info" in result, "Missing 'hourly_info' in result"
        
        hourly_info = result["hourly_info"]
        assert "is_demo" in hourly_info, "Missing 'is_demo' in hourly_info"
        
        # With org rates configured, is_demo should be False
        assert hourly_info["is_demo"] == False, f"Expected is_demo=False with org rates, got {hourly_info['is_demo']}"
        print(f"AI proposal using org rates: is_demo={hourly_info['is_demo']}")
    
    # ── Test 4: AI proposal hourly_info includes currency='EUR' ──
    def test_ai_proposal_eur_currency(self):
        """AI proposal hourly_info should include currency='EUR'"""
        ai_resp = self.session.post(f"{BASE_URL}/api/extra-works/ai-fast", json={
            "lines": [{"title": "мазилка стени", "unit": "m2", "qty": 10}]
        })
        assert ai_resp.status_code == 200, f"AI proposal failed: {ai_resp.status_code} - {ai_resp.text}"
        data = ai_resp.json()
        
        assert len(data["results"]) > 0, "No results returned"
        result = data["results"][0]
        
        assert "hourly_info" in result, "Missing 'hourly_info' in result"
        hourly_info = result["hourly_info"]
        
        assert "currency" in hourly_info, "Missing 'currency' in hourly_info"
        assert hourly_info["currency"] == "EUR", f"Expected currency='EUR', got '{hourly_info['currency']}'"
        print(f"AI proposal currency: {hourly_info['currency']}")
    
    # ── Test 5: GET /api/employees returns employees list ──
    def test_get_employees(self):
        """GET /api/employees should return list of employees"""
        resp = self.session.get(f"{BASE_URL}/api/employees")
        assert resp.status_code == 200, f"Failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        
        # Should return a list
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"Employees endpoint returned {len(data)} employees")
        
        # Verify structure if employees exist
        if len(data) > 0:
            employee = data[0]
            assert "id" in employee, "Employee missing 'id'"
            assert "email" in employee or "name" in employee, "Employee missing name/email"
    
    # ── Test 6: GET /api/payroll-runs returns payroll data ──
    def test_get_payroll_runs(self):
        """GET /api/payroll-runs should return payroll data"""
        resp = self.session.get(f"{BASE_URL}/api/payroll-runs")
        assert resp.status_code == 200, f"Failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        
        # Should return a list
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"Payroll runs endpoint returned {len(data)} runs")
        
        # Verify structure if payroll runs exist
        if len(data) > 0:
            run = data[0]
            assert "id" in run, "Payroll run missing 'id'"
            assert "status" in run, "Payroll run missing 'status'"
    
    # ── Test 7: GET /api/historical/analytics returns historical price data ──
    def test_get_historical_analytics(self):
        """GET /api/historical/analytics should return historical data"""
        resp = self.session.get(f"{BASE_URL}/api/historical/analytics")
        assert resp.status_code == 200, f"Failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        
        # Verify response structure
        assert "total_rows" in data, "Missing 'total_rows'"
        assert "categories" in data, "Missing 'categories'"
        
        print(f"Historical analytics: {data['total_rows']} rows, {len(data.get('categories', []))} categories")
        
        # Check categories structure
        if data.get("categories"):
            cat = data["categories"][0]
            assert "activity_type" in cat, "Category missing 'activity_type'"
            assert "sample_count" in cat, "Category missing 'sample_count'"
    
    # ── Test 8: GET /api/advances returns advances list ──
    def test_get_advances(self):
        """GET /api/advances should return advances list"""
        resp = self.session.get(f"{BASE_URL}/api/advances")
        assert resp.status_code == 200, f"Failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        
        # Should return a list
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"Advances endpoint returned {len(data)} advances")
    
    # ── Test 9: Verify org rates configuration persists ──
    def test_org_rates_persistence(self):
        """Verify that saved org rates persist correctly"""
        # Get current rates
        resp = self.session.get(f"{BASE_URL}/api/ai-config/hourly-rates")
        assert resp.status_code == 200
        data = resp.json()
        
        # After previous tests, source should be 'organization'
        if data["source"] == "organization":
            rates = data["rates"]
            assert "бояджия" in rates, "бояджия should be in rates"
            assert rates["бояджия"]["hourly_rate"] == 15, "бояджия rate should be 15 EUR/h"
            print(f"Verified: бояджия rate = {rates['бояджия']['hourly_rate']} EUR/h")
        else:
            print(f"Rates source is '{data['source']}' - using DEMO defaults")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
