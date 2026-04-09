"""
Tests for Infrastructure: error middleware, pagination.
Run: pytest backend/tests/test_infrastructure.py -v
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


# ── Test 1: Error middleware passes normal requests ─────────────────

def test_error_middleware_normal(auth_headers):
    r = httpx.get(f"{API}/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert "id" in r.json()


# ── Test 2: Error middleware catches 404 ────────────────────────────

def test_error_middleware_404(auth_headers):
    r = httpx.get(f"{API}/nonexistent-endpoint-xyz", headers=auth_headers)
    assert r.status_code in [404, 405, 422]


# ── Test 3: Paginate query returns correct page (work-sessions) ────

def test_pagination_page1(auth_headers):
    r = httpx.get(f"{API}/work-sessions?page=1&page_size=5", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d
    assert "total" in d
    assert "page" in d
    assert d["page"] == 1
    assert d["page_size"] == 5
    assert "total_pages" in d
    assert "has_next" in d
    assert "has_prev" in d
    assert d["has_prev"] is False  # page 1 has no prev


# ── Test 4: Paginate returns correct total ──────────────────────────

def test_pagination_total(auth_headers):
    r = httpx.get(f"{API}/work-sessions?page=1&page_size=3", headers=auth_headers)
    d = r.json()
    assert d["total"] >= 0
    assert d["total_pages"] == (d["total"] + 2) // 3 if d["total"] > 0 else 0


# ── Test 5: Paginate page 2 ─────────────────────────────────────────

def test_pagination_page2(auth_headers):
    r1 = httpx.get(f"{API}/work-sessions?page=1&page_size=2", headers=auth_headers)
    total = r1.json()["total"]

    if total > 2:
        r2 = httpx.get(f"{API}/work-sessions?page=2&page_size=2", headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["page"] == 2
        assert r2.json()["has_prev"] is True
        assert len(r2.json()["items"]) <= 2


# ── Test 6: Paginate empty result ───────────────────────────────────

def test_pagination_empty(auth_headers):
    r = httpx.get(f"{API}/alarms?status=nonexistent_status&page=1&page_size=10", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["items"] == []
    assert d["total"] == 0
    assert d["total_pages"] == 0
    assert d["has_next"] is False


# ── Test 7: Pagination on missing-smr ───────────────────────────────

def test_pagination_missing_smr(auth_headers):
    r = httpx.get(f"{API}/missing-smr?page=1&page_size=3", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d
    assert "page" in d
    assert len(d["items"]) <= 3


# ── Test 8: Pagination on smr-analyses ──────────────────────────────

def test_pagination_smr_analyses(auth_headers):
    r = httpx.get(f"{API}/smr-analyses?page=1&page_size=5", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "page" in d
    assert "total_pages" in d
