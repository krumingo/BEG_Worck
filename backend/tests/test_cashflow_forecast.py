"""
Tests for Cash Flow Forecast.
Run: pytest backend/tests/test_cashflow_forecast.py -v
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


# ── Test 1: Full forecast structure ────────────────────────────────

def test_forecast_structure(auth_headers):
    r = httpx.get(f"{API}/cashflow/forecast", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "headline" in d
    assert "summary" in d
    assert "timeline" in d
    assert "incoming" in d
    assert "outgoing" in d
    assert "overdue" in d


# ── Test 2: Summary has required fields ────────────────────────────

def test_summary_fields(auth_headers):
    d = httpx.get(f"{API}/cashflow/forecast", headers=auth_headers).json()
    s = d["summary"]
    assert "period_days" in s
    assert "total_incoming" in s
    assert "total_outgoing" in s
    assert "net_forecast" in s
    assert "overdue_receivables" in s
    assert "warning_level" in s
    assert s["warning_level"] in ["ok", "watch", "risk", "critical"]


# ── Test 3: Timeline has correct length ────────────────────────────

def test_timeline_length(auth_headers):
    d = httpx.get(f"{API}/cashflow/forecast?days=7", headers=auth_headers).json()
    assert len(d["timeline"]) == 8  # days + 1 (inclusive)
    for day in d["timeline"]:
        assert "date" in day
        assert "incoming" in day
        assert "outgoing" in day
        assert "net" in day
        assert "cumulative" in day


# ── Test 4: Cumulative net is correct ──────────────────────────────

def test_cumulative_net(auth_headers):
    d = httpx.get(f"{API}/cashflow/forecast?days=5", headers=auth_headers).json()
    cum = 0
    for day in d["timeline"]:
        cum = round(cum + day["net"], 2)
        assert abs(day["cumulative"] - cum) < 0.02


# ── Test 5: Warning level computation ──────────────────────────────

def test_warning_level(auth_headers):
    d = httpx.get(f"{API}/cashflow/forecast", headers=auth_headers).json()
    wl = d["summary"]["warning_level"]
    neg = d["summary"]["negative_days"]
    # If no negative days, should be ok or watch
    if neg == 0:
        assert wl in ["ok", "watch"]


# ── Test 6: Compact endpoint ──────────────────────────────────────

def test_compact(auth_headers):
    r = httpx.get(f"{API}/cashflow/forecast/compact", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "headline" in d
    assert "warning_level" in d
    assert "net_forecast" in d
    assert "top_incoming" in d
    assert "top_outgoing" in d
    assert len(d["top_incoming"]) <= 3
    assert len(d["top_outgoing"]) <= 3


# ── Test 7: Headline is string ─────────────────────────────────────

def test_headline(auth_headers):
    d = httpx.get(f"{API}/cashflow/forecast", headers=auth_headers).json()
    assert isinstance(d["headline"], str)
    assert len(d["headline"]) > 10


# ── Test 8: Safe empty / future response ───────────────────────────

def test_empty_safe(auth_headers):
    r = httpx.get(f"{API}/cashflow/forecast?days=5&start_date=2099-01-01", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["total_incoming"] >= 0
    assert d["summary"]["total_outgoing"] >= 0
