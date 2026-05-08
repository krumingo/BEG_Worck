"""
Tests for Expected vs Actual comparison.
Run: pytest backend/tests/test_expected_actual.py -v
"""
import pytest
import httpx
from pathlib import Path

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
    projects = r.json() if isinstance(r.json(), list) else r.json()
    return projects[0]["id"]


# ── Test 1: Full structure ─────────────────────────────────────────

def test_full_structure(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/expected-actual", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "summary" in d
    assert "activities" in d
    assert "groups" in d
    assert "locations" in d


# ── Test 2: Summary fields ─────────────────────────────────────────

def test_summary(auth_headers, project_id):
    d = httpx.get(f"{API}/projects/{project_id}/expected-actual", headers=auth_headers).json()
    s = d["summary"]
    assert "total_planned_hours" in s
    assert "total_actual_hours" in s
    assert "total_planned_cost" in s
    assert "total_actual_cost" in s
    assert "overall_status" in s
    assert s["overall_status"] in ["on_track", "warning", "over"]


# ── Test 3: Activities have required fields ────────────────────────

def test_activities(auth_headers, project_id):
    d = httpx.get(f"{API}/projects/{project_id}/expected-actual", headers=auth_headers).json()
    for a in d["activities"]:
        assert "name" in a
        assert "planned_hours" in a
        assert "actual_hours" in a
        assert "variance_cost" in a
        assert "status" in a
        assert a["status"] in ["on_track", "warning", "over"]


# ── Test 4: Groups comparison ──────────────────────────────────────

def test_groups(auth_headers, project_id):
    d = httpx.get(f"{API}/projects/{project_id}/expected-actual", headers=auth_headers).json()
    assert isinstance(d["groups"], list)
    for g in d["groups"]:
        assert "name" in g
        assert "planned_cost" in g
        assert "actual_cost" in g


# ── Test 5: Locations comparison ───────────────────────────────────

def test_locations(auth_headers, project_id):
    d = httpx.get(f"{API}/projects/{project_id}/expected-actual", headers=auth_headers).json()
    assert isinstance(d["locations"], list)


# ── Test 6: Warning at 80% ────────────────────────────────────────

def test_status_logic():
    from app.services.expected_actual import _status
    assert _status(79, 100) == "on_track"
    assert _status(80, 100) == "warning"
    assert _status(99, 100) == "warning"
    assert _status(101, 100) == "over"
    assert _status(0, 0) == "on_track"
    assert _status(50, 0) == "over"


# ── Test 7: Compact endpoint ──────────────────────────────────────

def test_compact(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/expected-actual/compact", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "summary" in d
    assert "top_overruns" in d
    assert "activities" in d["top_overruns"]
    assert len(d["top_overruns"]["activities"]) <= 3


# ── Test 8: Empty project ──────────────────────────────────────────

def test_empty_project(auth_headers):
    import uuid
    code = f"EVA-{str(uuid.uuid4())[:5]}"
    p = httpx.post(f"{API}/projects", json={"code": code, "name": "EVA Empty"}, headers=auth_headers).json()
    r = httpx.get(f"{API}/projects/{p['id']}/expected-actual", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["total_planned_hours"] == 0
    assert d["summary"]["total_actual_hours"] == 0
    assert len(d["activities"]) == 0
