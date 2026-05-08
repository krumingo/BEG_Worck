"""
Tests for Work Sessions (BEG SiteClock) module.
Run: pytest backend/tests/test_work_sessions.py -v
"""
import pytest
import httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta

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


@pytest.fixture(scope="module")
def auth_headers():
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    projects = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    return projects[0]["id"]


# ── Test 1: Start session ─────────────────────────────────────────

def test_start_session(auth_headers, project_id):
    r = httpx.post(f"{API}/work-sessions/start", json={
        "site_id": project_id,
        "source_method": "SELF_REPORT",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["site_id"] == project_id
    assert d["ended_at"] is None
    assert d["hourly_rate_at_date"] is not None
    assert d["started_at"] is not None


# ── Test 2: End session (normal) ──────────────────────────────────

def test_end_session(auth_headers):
    r = httpx.post(f"{API}/work-sessions/end", json={
        "notes": "Done for now",
    }, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["ended_at"] is not None
    assert d["duration_hours"] is not None
    assert d["duration_hours"] >= 0
    assert d["labor_cost"] is not None


# ── Test 3: Start with existing open → auto-close ─────────────────

def test_auto_close_on_new_start(auth_headers, project_id):
    # Start first session
    r1 = httpx.post(f"{API}/work-sessions/start", json={
        "site_id": project_id,
    }, headers=auth_headers)
    assert r1.status_code == 201
    first_id = r1.json()["id"]

    # Start second session (should auto-close first)
    r2 = httpx.post(f"{API}/work-sessions/start", json={
        "site_id": project_id,
    }, headers=auth_headers)
    assert r2.status_code == 201
    assert r2.json().get("auto_closed_session_id") == first_id

    # Verify first session is closed and flagged
    r3 = httpx.get(f"{API}/work-sessions", headers=auth_headers)
    items = r3.json()["items"]
    first = next((s for s in items if s["id"] == first_id), None)
    assert first is not None
    assert first["ended_at"] is not None
    assert first["is_flagged"] is True
    assert first["flag_reason"] == "auto_closed"

    # Clean up - end the second session
    httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)


# ── Test 4: Hourly rate snapshot (monthly employee) ────────────────

def test_hourly_rate_snapshot(auth_headers, project_id):
    # Start and immediately end
    r = httpx.post(f"{API}/work-sessions/start", json={"site_id": project_id}, headers=auth_headers)
    assert r.status_code == 201
    rate = r.json()["hourly_rate_at_date"]
    assert rate is not None
    # Rate should be a reasonable number (0 if no profile, or > 0 if profile exists)
    assert rate >= 0
    httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)


# ── Test 5: My-today endpoint ──────────────────────────────────────

def test_my_today(auth_headers):
    r = httpx.get(f"{API}/work-sessions/my-today", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d
    assert "total_hours" in d
    assert "total_cost" in d
    assert "has_open_session" in d
    assert "is_overtime" in d


# ── Test 6: Summary endpoint ──────────────────────────────────────

def test_summary(auth_headers, project_id):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = httpx.get(f"{API}/work-sessions/summary?date={today}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "total_hours" in d
    assert "total_cost" in d
    assert "workers_count" in d


# ── Test 7: Active sessions ───────────────────────────────────────

def test_active_sessions(auth_headers, project_id):
    # Start a session
    httpx.post(f"{API}/work-sessions/start", json={"site_id": project_id}, headers=auth_headers)
    
    r = httpx.get(f"{API}/work-sessions/active", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    # Active sessions should have elapsed_hours
    for s in r.json()["items"]:
        assert "elapsed_hours" in s

    # Clean up
    httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)


# ── Test 8: Split session ─────────────────────────────────────────

def test_split_session(auth_headers, project_id):
    # Create and end a session
    httpx.post(f"{API}/work-sessions/start", json={"site_id": project_id}, headers=auth_headers)
    import time; time.sleep(0.5)
    end_r = httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)
    session_id = end_r.json()["id"]

    # Split it
    r = httpx.post(f"{API}/work-sessions/{session_id}/split", json={
        "splits": [
            {"smr_type_id": "masonry", "hours": 1.0},
            {"smr_type_id": "painting", "hours": 0.5},
        ],
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(r.json()["new_sessions"]) == 2


# ── Test 9: Overtime report ───────────────────────────────────────

def test_overtime_report(auth_headers):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = httpx.get(f"{API}/work-sessions/overtime?date_from={today}&date_to={today}", headers=auth_headers)
    assert r.status_code == 200
    assert "workers" in r.json()


# ── Test 10: Update session (admin) ───────────────────────────────

def test_update_session(auth_headers, project_id):
    httpx.post(f"{API}/work-sessions/start", json={"site_id": project_id}, headers=auth_headers)
    end_r = httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)
    sid = end_r.json()["id"]

    r = httpx.put(f"{API}/work-sessions/{sid}", json={
        "notes": "Updated by admin",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["notes"] == "Updated by admin"


# ── Test 11: Cannot end without open session ──────────────────────

def test_end_no_open(auth_headers):
    # Make sure no open session
    httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)
    r = httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)
    assert r.status_code == 404


# ── Test 12: List with filters ────────────────────────────────────

def test_list_sessions(auth_headers, project_id):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = httpx.get(f"{API}/work-sessions?site_id={project_id}&date={today}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
