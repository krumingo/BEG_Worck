"""
Tests for Morning Briefing.
Run: pytest backend/tests/test_morning_briefing.py -v
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


# ── Test 1: Briefing returns full structure ────────────────────────

def test_briefing_structure(auth_headers):
    r = httpx.get(f"{API}/morning-briefing", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "date" in d
    assert "headline" in d
    assert "summary" in d
    assert "top_risks" in d
    assert "payments" in d
    assert "missing_reports" in d
    assert "overhead" in d
    assert "top_alarms" in d


# ── Test 2: Summary has required fields ────────────────────────────

def test_summary_fields(auth_headers):
    d = httpx.get(f"{API}/morning-briefing", headers=auth_headers).json()
    s = d["summary"]
    assert "active_projects" in s
    assert "workers_today" in s
    assert "critical_alarms" in s
    assert "due_payments_count" in s


# ── Test 3: Headline is non-empty string ───────────────────────────

def test_headline(auth_headers):
    d = httpx.get(f"{API}/morning-briefing", headers=auth_headers).json()
    assert isinstance(d["headline"], str)
    assert len(d["headline"]) > 5


# ── Test 4: Top risks are limited to 3 ────────────────────────────

def test_risks_limited(auth_headers):
    d = httpx.get(f"{API}/morning-briefing", headers=auth_headers).json()
    assert len(d["top_risks"]) <= 3
    for r in d["top_risks"]:
        assert "project_id" in r
        assert "project_name" in r
        assert "severity" in r
        assert "reasons" in r


# ── Test 5: Payments have urgency field ────────────────────────────

def test_payments(auth_headers):
    d = httpx.get(f"{API}/morning-briefing", headers=auth_headers).json()
    assert isinstance(d["payments"], list)
    for p in d["payments"]:
        assert p.get("urgency") in ["overdue", "due_soon"]
        assert "unpaid" in p


# ── Test 6: Compact endpoint ──────────────────────────────────────

def test_compact(auth_headers):
    r = httpx.get(f"{API}/morning-briefing/compact", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "headline" in d
    assert "critical_count" in d
    assert "warning_count" in d
    assert "top_risks" in d
    assert len(d["top_risks"]) <= 3


# ── Test 7: Overhead section ──────────────────────────────────────

def test_overhead(auth_headers):
    d = httpx.get(f"{API}/morning-briefing", headers=auth_headers).json()
    oh = d["overhead"]
    assert "overhead_per_person_day" in oh
    assert "working_today" in oh
    assert "total_employees" in oh


# ── Test 8: Safe empty response ────────────────────────────────────

def test_empty_safe(auth_headers):
    # Even with a future date where nothing exists, should not crash
    r = httpx.get(f"{API}/morning-briefing?date=2099-12-31", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["date"] == "2099-12-31"
    assert isinstance(d["headline"], str)
    assert d["summary"]["critical_alarms"] >= 0
