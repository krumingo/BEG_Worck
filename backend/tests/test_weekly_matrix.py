"""
Test Weekly Matrix API (GET /api/weekly-matrix)
Tests for the Sat→Fri payroll week matrix feature.
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from iteration_62.json
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "AdminTest123!Secure"


class TestWeeklyMatrixAPI:
    """Weekly Matrix endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - get auth token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            self.authenticated = True
        else:
            self.authenticated = False
            pytest.skip(f"Authentication failed: {response.status_code}")
    
    # ===== Basic API Tests =====
    
    def test_weekly_matrix_returns_200(self):
        """GET /api/weekly-matrix returns 200"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/weekly-matrix returns 200")
    
    def test_response_has_required_fields(self):
        """Response has week_start, week_end, dates, rows, totals"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["week_start", "week_end", "dates", "rows", "totals"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"✓ Response has all required fields: {required_fields}")
    
    def test_dates_array_has_7_days(self):
        """dates array contains exactly 7 days"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["dates"]) == 7, f"Expected 7 dates, got {len(data['dates'])}"
        print(f"✓ dates array has 7 days: {data['dates']}")
    
    def test_week_starts_on_saturday(self):
        """Week starts on Saturday (day 0 of payroll week)"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        week_start = datetime.strptime(data["week_start"], "%Y-%m-%d")
        # Saturday = weekday 5 in Python
        assert week_start.weekday() == 5, f"Week start should be Saturday (5), got {week_start.weekday()}"
        print(f"✓ Week starts on Saturday: {data['week_start']} (weekday={week_start.weekday()})")
    
    def test_week_ends_on_friday(self):
        """Week ends on Friday (day 6 of payroll week)"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        week_end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        # Friday = weekday 4 in Python
        assert week_end.weekday() == 4, f"Week end should be Friday (4), got {week_end.weekday()}"
        print(f"✓ Week ends on Friday: {data['week_end']} (weekday={week_end.weekday()})")
    
    def test_week_span_is_6_days(self):
        """Week span is exactly 6 days (Sat to Fri)"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        week_start = datetime.strptime(data["week_start"], "%Y-%m-%d")
        week_end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        span = (week_end - week_start).days
        
        assert span == 6, f"Expected 6 days span, got {span}"
        print(f"✓ Week span is 6 days: {data['week_start']} → {data['week_end']}")
    
    # ===== week_of Parameter Tests =====
    
    def test_week_of_parameter_returns_correct_week(self):
        """GET /api/weekly-matrix?week_of=2026-04-11 returns Sat Apr 11 → Fri Apr 17"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix?week_of=2026-04-11")
        assert response.status_code == 200
        data = response.json()
        
        assert data["week_start"] == "2026-04-11", f"Expected week_start=2026-04-11, got {data['week_start']}"
        assert data["week_end"] == "2026-04-17", f"Expected week_end=2026-04-17, got {data['week_end']}"
        print(f"✓ week_of=2026-04-11 returns correct week: {data['week_start']} → {data['week_end']}")
    
    def test_week_of_mid_week_date(self):
        """week_of with mid-week date returns containing Sat→Fri week"""
        # Wednesday April 15, 2026 should return Sat Apr 11 → Fri Apr 17
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix?week_of=2026-04-15")
        assert response.status_code == 200
        data = response.json()
        
        assert data["week_start"] == "2026-04-11", f"Expected week_start=2026-04-11, got {data['week_start']}"
        assert data["week_end"] == "2026-04-17", f"Expected week_end=2026-04-17, got {data['week_end']}"
        print(f"✓ week_of=2026-04-15 (Wed) returns containing week: {data['week_start']} → {data['week_end']}")
    
    def test_week_of_friday_date(self):
        """week_of with Friday date returns containing Sat→Fri week"""
        # Friday April 17, 2026 should return Sat Apr 11 → Fri Apr 17
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix?week_of=2026-04-17")
        assert response.status_code == 200
        data = response.json()
        
        assert data["week_start"] == "2026-04-11", f"Expected week_start=2026-04-11, got {data['week_start']}"
        assert data["week_end"] == "2026-04-17", f"Expected week_end=2026-04-17, got {data['week_end']}"
        print(f"✓ week_of=2026-04-17 (Fri) returns containing week: {data['week_start']} → {data['week_end']}")
    
    # ===== Row Structure Tests =====
    
    def test_row_has_required_fields(self):
        """Each row has worker info, days array, and summary fields"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["rows"]) == 0:
            pytest.skip("No rows in response - no workers with data")
        
        row = data["rows"][0]
        required_fields = [
            "worker_id", "first_name", "last_name", "days",
            "total_hours", "worked_days", "hourly_rate", "labor_value",
            "bonuses", "deductions", "net_pay"
        ]
        
        for field in required_fields:
            assert field in row, f"Missing required field in row: {field}"
        
        print(f"✓ Row has all required fields: {required_fields}")
    
    def test_row_days_array_has_7_entries(self):
        """Each row's days array has exactly 7 entries"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["rows"]) == 0:
            pytest.skip("No rows in response")
        
        for i, row in enumerate(data["rows"]):
            assert len(row["days"]) == 7, f"Row {i} has {len(row['days'])} days, expected 7"
        
        print(f"✓ All {len(data['rows'])} rows have 7 days each")
    
    def test_day_entry_has_required_fields(self):
        """Each day entry has date, hours, normal, overtime, entries, has_data"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["rows"]) == 0:
            pytest.skip("No rows in response")
        
        day = data["rows"][0]["days"][0]
        required_fields = ["date", "hours", "normal", "overtime", "entries", "has_data"]
        
        for field in required_fields:
            assert field in day, f"Missing required field in day: {field}"
        
        print(f"✓ Day entry has all required fields: {required_fields}")
    
    # ===== Totals Tests =====
    
    def test_totals_has_required_fields(self):
        """Totals include hours, normal, overtime, value, workers, workers_with_data"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        totals = data["totals"]
        required_fields = ["hours", "normal", "overtime", "value", "workers", "workers_with_data"]
        
        for field in required_fields:
            assert field in totals, f"Missing required field in totals: {field}"
        
        print(f"✓ Totals has all required fields: {totals}")
    
    def test_totals_math_consistency(self):
        """Totals hours = normal + overtime"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        totals = data["totals"]
        expected_hours = totals["normal"] + totals["overtime"]
        
        # Allow small floating point difference
        assert abs(totals["hours"] - expected_hours) < 0.1, \
            f"Totals hours ({totals['hours']}) != normal ({totals['normal']}) + overtime ({totals['overtime']})"
        
        print(f"✓ Totals math consistent: {totals['hours']} = {totals['normal']} + {totals['overtime']}")
    
    def test_workers_with_data_count(self):
        """workers_with_data <= workers"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        totals = data["totals"]
        assert totals["workers_with_data"] <= totals["workers"], \
            f"workers_with_data ({totals['workers_with_data']}) > workers ({totals['workers']})"
        
        print(f"✓ workers_with_data ({totals['workers_with_data']}) <= workers ({totals['workers']})")
    
    # ===== Overtime Calculation Tests =====
    
    def test_overtime_calculated_correctly(self):
        """Overtime is calculated when day hours > 8 (NORMAL_DAY)"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        NORMAL_DAY = 8
        
        for row in data["rows"]:
            for day in row["days"]:
                if day["hours"] > 0:
                    expected_normal = min(day["hours"], NORMAL_DAY)
                    expected_overtime = max(0, day["hours"] - NORMAL_DAY)
                    
                    assert abs(day["normal"] - expected_normal) < 0.1, \
                        f"Day normal hours mismatch: {day['normal']} != {expected_normal}"
                    assert abs(day["overtime"] - expected_overtime) < 0.1, \
                        f"Day overtime hours mismatch: {day['overtime']} != {expected_overtime}"
        
        print("✓ Overtime calculated correctly (>8h = overtime)")
    
    # ===== Authentication Tests =====
    
    def test_unauthenticated_request_rejected(self):
        """Unauthenticated request returns 401/403"""
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/weekly-matrix")
        
        assert response.status_code in [401, 403], \
            f"Expected 401/403 for unauthenticated request, got {response.status_code}"
        
        print(f"✓ Unauthenticated request rejected with {response.status_code}")
    
    # ===== Data Verification Tests =====
    
    def test_dates_match_week_range(self):
        """All dates in dates array are within week_start to week_end"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        week_start = datetime.strptime(data["week_start"], "%Y-%m-%d")
        week_end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        
        for date_str in data["dates"]:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            assert week_start <= date <= week_end, \
                f"Date {date_str} is outside week range {data['week_start']} - {data['week_end']}"
        
        print(f"✓ All dates within week range: {data['dates']}")
    
    def test_row_days_dates_match_header_dates(self):
        """Row days dates match the header dates array"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["rows"]) == 0:
            pytest.skip("No rows in response")
        
        for row in data["rows"]:
            row_dates = [day["date"] for day in row["days"]]
            assert row_dates == data["dates"], \
                f"Row dates {row_dates} don't match header dates {data['dates']}"
        
        print("✓ All row days dates match header dates")
    
    def test_labor_value_calculation(self):
        """labor_value = total_hours * hourly_rate"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        for row in data["rows"]:
            if row["total_hours"] > 0 and row["hourly_rate"] > 0:
                expected_value = round(row["total_hours"] * row["hourly_rate"], 2)
                assert abs(row["labor_value"] - expected_value) < 0.1, \
                    f"Labor value mismatch: {row['labor_value']} != {expected_value}"
        
        print("✓ Labor value calculated correctly (hours * rate)")
    
    def test_net_pay_equals_labor_value(self):
        """net_pay = labor_value (since bonuses=0, deductions=0)"""
        response = self.session.get(f"{BASE_URL}/api/weekly-matrix")
        assert response.status_code == 200
        data = response.json()
        
        for row in data["rows"]:
            # net_pay = labor_value + bonuses - deductions
            expected_net = row["labor_value"] + row["bonuses"] - row["deductions"]
            assert abs(row["net_pay"] - expected_net) < 0.1, \
                f"Net pay mismatch: {row['net_pay']} != {expected_net}"
        
        print("✓ Net pay calculated correctly (labor + bonuses - deductions)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
