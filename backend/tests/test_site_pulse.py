"""
Tests for Site Pulse module.
Run: pytest backend/tests/test_site_pulse.py -v
"""
import pytest
import httpx
from pathlib import Path
from datetime import datetime, timezone

BASE_URL = ""
fe_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
if fe_env.exists():
    for line in fe_env.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"
EMAIL = "admin@begwork.com"
PASSWORD = "AdminTest123!Secure"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def auth_headers():
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    projects = r.json() if isinstance(r.json(), list) else r.json()
    return projects[0]["id"]


# ── Test 1: Generate pulse for site ────────────────────────────────

def test_generate_pulse(auth_headers, project_id):
    r = httpx.post(f"{API}/sites/{project_id}/pulse/generate?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["site_id"] == project_id
    assert d["date"] == TODAY
    assert "workers" in d
    assert "total_workers" in d
    assert "total_hours" in d
    assert "budget_snapshot" in d
    assert "alerts" in d


# ── Test 2: Get pulse (auto-generate on demand) ───────────────────

def test_get_pulse(auth_headers, project_id):
    r = httpx.get(f"{API}/sites/{project_id}/pulse?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["site_id"] == project_id


# ── Test 3: Pulse with no data (empty project) ────────────────────

def test_pulse_empty(auth_headers):
    import uuid
    code = f"PULSE-{str(uuid.uuid4())[:5]}"
    p = httpx.post(f"{API}/projects", json={"code": code, "name": "Empty Pulse"}, headers=auth_headers).json()

    r = httpx.get(f"{API}/sites/{p['id']}/pulse?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total_workers"] == 0
    assert d["total_hours"] == 0
    # Should have "no_workers" alert
    alert_types = [a["type"] for a in d["alerts"]]
    assert "no_workers" in alert_types


# ── Test 4: Pulse with overtime alert ──────────────────────────────

def test_pulse_overtime(auth_headers, project_id):
    # Work sessions with overtime exist from previous tests
    r = httpx.get(f"{API}/sites/{project_id}/pulse?date={TODAY}", headers=auth_headers)
    d = r.json()
    # Check structure is correct
    assert "overtime_hours" in d
    assert "alerts" in d


# ── Test 5: Pulse with budget warning ──────────────────────────────

def test_pulse_budget(auth_headers, project_id):
    r = httpx.get(f"{API}/sites/{project_id}/pulse?date={TODAY}", headers=auth_headers)
    d = r.json()
    bs = d["budget_snapshot"]
    assert "total_budget" in bs
    assert "burn_pct" in bs
    assert bs["status"] in ["on_track", "warning", "over_budget"]


# ── Test 6: Pulse today (multiple sites) ───────────────────────────

def test_pulse_today(auth_headers):
    r = httpx.get(f"{API}/pulse/today", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()
    assert r.json()["total"] >= 1


# ── Test 7: Pulse range ────────────────────────────────────────────

def test_pulse_range(auth_headers, project_id):
    r = httpx.get(f"{API}/sites/{project_id}/pulse/range?date_from={TODAY}&date_to={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()


# ── Test 8: Generate all ───────────────────────────────────────────

def test_generate_all(auth_headers):
    r = httpx.post(f"{API}/pulse/generate-all?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["generated"] >= 1


# ── Test 9: Pulse summary ─────────────────────────────────────────

def test_pulse_summary(auth_headers):
    r = httpx.get(f"{API}/pulse/summary?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "sites_count" in d
    assert "total_workers" in d
    assert "total_hours" in d
    assert "alerts_count" in d
    assert "alerts" in d
