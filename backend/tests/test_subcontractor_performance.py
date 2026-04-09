"""
Tests for Subcontractor Performance.
Run: pytest backend/tests/test_subcontractor_performance.py -v
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


# ── Test 1: Empty summary ──────────────────────────────────────────

def test_empty_summary(auth_headers):
    r = httpx.get(f"{API}/subcontractor-performance", headers=auth_headers)
    assert r.status_code == 200
    assert "summary" in r.json()
    assert "items" in r.json()


# ── Test 2: Create record ──────────────────────────────────────────

def test_create(auth_headers, project_id):
    r = httpx.post(f"{API}/subcontractor-performance", json={
        "subcontractor_id": "sub-ivan-001",
        "project_id": project_id,
        "promised_start_date": "2026-03-01",
        "promised_end_date": "2026-04-01",
        "actual_start_date": "2026-03-05",
        "actual_end_date": "2026-04-15",
        "promised_amount": 5000,
        "actual_paid_amount": 5500,
        "quality_score": 3,
        "notes": "Забави 2 седмици, надхвърли бюджет",
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["subcontractor_id"] == "sub-ivan-001"


# ── Test 3: Update record ──────────────────────────────────────────

def test_update(auth_headers):
    items = httpx.get(f"{API}/subcontractor-performance/log", headers=auth_headers).json()["items"]
    rid = items[0]["id"]
    r = httpx.put(f"{API}/subcontractor-performance/{rid}", json={
        "quality_score": 4, "notes": "Updated",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["quality_score"] == 4


# ── Test 4: Delayed status ─────────────────────────────────────────

def test_delayed(auth_headers, project_id):
    httpx.post(f"{API}/subcontractor-performance", json={
        "subcontractor_id": "sub-delayed",
        "project_id": project_id,
        "promised_end_date": "2026-03-01",
        "actual_end_date": "2026-04-01",
        "promised_amount": 3000,
        "actual_paid_amount": 2800,
    }, headers=auth_headers)
    d = httpx.get(f"{API}/subcontractor-performance", headers=auth_headers).json()
    delayed = [i for i in d["items"] if i.get("subcontractor_id") == "sub-delayed"]
    assert len(delayed) >= 1
    assert delayed[0]["status"] == "delayed"


# ── Test 5: Over budget status ─────────────────────────────────────

def test_over_budget(auth_headers, project_id):
    httpx.post(f"{API}/subcontractor-performance", json={
        "subcontractor_id": "sub-expensive",
        "project_id": project_id,
        "promised_end_date": "2026-05-01",
        "actual_end_date": "2026-04-20",
        "promised_amount": 2000,
        "actual_paid_amount": 3000,
    }, headers=auth_headers)
    d = httpx.get(f"{API}/subcontractor-performance", headers=auth_headers).json()
    over = [i for i in d["items"] if i.get("subcontractor_id") == "sub-expensive"]
    assert over[0]["status"] == "over_budget"


# ── Test 6: Mixed status ──────────────────────────────────────────

def test_mixed(auth_headers, project_id):
    httpx.post(f"{API}/subcontractor-performance", json={
        "subcontractor_id": "sub-mixed",
        "project_id": project_id,
        "promised_end_date": "2026-03-01",
        "actual_end_date": "2026-04-01",
        "promised_amount": 2000,
        "actual_paid_amount": 3000,
    }, headers=auth_headers)
    d = httpx.get(f"{API}/subcontractor-performance", headers=auth_headers).json()
    mixed = [i for i in d["items"] if i.get("subcontractor_id") == "sub-mixed"]
    assert mixed[0]["status"] == "mixed"


# ── Test 7: Compact endpoint ──────────────────────────────────────

def test_compact(auth_headers):
    r = httpx.get(f"{API}/subcontractor-performance/compact", headers=auth_headers)
    assert r.status_code == 200
    assert "summary" in r.json()
    assert "top_delays" in r.json()
    assert "top_over_budget" in r.json()


# ── Test 8: Log endpoint ──────────────────────────────────────────

def test_log(auth_headers):
    r = httpx.get(f"{API}/subcontractor-performance/log", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 4
