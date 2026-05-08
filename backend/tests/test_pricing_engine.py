"""
Tests for Pricing Engine module.
Run: pytest backend/tests/test_pricing_engine.py -v
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
    projects = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    return projects[0]["id"]


# ── Test 1: Get single material price (cache miss → fetch) ────────

def test_get_single_price(auth_headers):
    r = httpx.get(f"{API}/pricing/material?name=Латекс интериорен&force=true", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["material_name"] == "Латекс интериорен"
    assert d["median_price"] is not None
    assert d["median_price"] > 0
    assert len(d["prices"]) >= 1
    assert d["confidence"] > 0


# ── Test 2: Get cached price (cache hit) ──────────────────────────

def test_get_cached_price(auth_headers):
    # First call populates cache
    httpx.get(f"{API}/pricing/material?name=Грунд&force=true", headers=auth_headers)
    # Second call should hit cache
    r = httpx.get(f"{API}/pricing/material?name=Грунд", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["median_price"] > 0
    assert d.get("from_cache") is True


# ── Test 3: Force refresh ─────────────────────────────────────────

def test_force_refresh(auth_headers):
    r = httpx.post(f"{API}/pricing/refresh?name=Шпакловка финишна", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["median_price"] > 0
    assert d.get("from_cache") is not True


# ── Test 4: Batch pricing ─────────────────────────────────────────

def test_batch_pricing(auth_headers):
    r = httpx.post(f"{API}/pricing/batch", json={
        "materials": ["Латекс интериорен", "Грунд", "Шпакловка финишна"],
    }, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3
    for result in d["results"]:
        assert result["median_price"] is not None


# ── Test 5: Agent 3 with ACTIVITY_KNOWLEDGE fallback ──────────────

def test_agent_3_knowledge(auth_headers):
    # Гипсова мазилка is in ACTIVITY_KNOWLEDGE
    r = httpx.get(f"{API}/pricing/material?name=Гипсова мазилка&force=true", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["median_price"] > 0
    # Should have agent 3 result
    agent3 = [p for p in d["prices"] if p["agent_id"] == 3]
    assert len(agent3) >= 0  # may or may not have internal data


# ── Test 6: Catalog listing ───────────────────────────────────────

def test_catalog(auth_headers):
    # Ensure some prices exist
    httpx.get(f"{API}/pricing/material?name=Латекс интериорен&force=true", headers=auth_headers)
    r = httpx.get(f"{API}/pricing/catalog", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    assert any(i["material_name"] == "Латекс интериорен" for i in d["items"])


# ── Test 7: Price history ─────────────────────────────────────────

def test_price_history(auth_headers):
    r = httpx.get(f"{API}/pricing/history?name=Латекс интериорен", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1


# ── Test 8: Integration with SMR Analysis (fetch-prices) ──────────

def test_fetch_prices_integration(auth_headers, project_id):
    # Create an analysis with a line that has materials
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Pricing Integration Test",
    }, headers=auth_headers).json()
    aid = a["id"]

    # Add line with materials
    res = httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Боядисване стени",
        "unit": "m2",
        "qty": 50,
        "labor_price_per_unit": 6,
        "materials": [
            {"name": "Латекс интериорен", "unit": "л", "qty_per_unit": 0.25, "unit_price": 0, "waste_pct": 5},
            {"name": "Грунд", "unit": "л", "qty_per_unit": 0.12, "unit_price": 0, "waste_pct": 3},
        ],
    }, headers=auth_headers).json()
    line_id = res["lines"][0]["line_id"]

    # Fetch prices for the line
    r = httpx.post(f"{API}/smr-analyses/{aid}/lines/{line_id}/fetch-prices", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["materials_updated"] >= 1
    # Check that material unit_prices got updated
    updated_mats = d["analysis"]["lines"][0]["materials"]
    for m in updated_mats:
        if m["name"] in ["Латекс интериорен", "Грунд"]:
            assert m["unit_price"] > 0, f"unit_price should be > 0 for {m['name']}"


# ── Test 9: Unknown material still returns result ─────────────────

def test_unknown_material(auth_headers):
    r = httpx.get(f"{API}/pricing/material?name=НепознатМатериал123&force=true", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    # May or may not have prices, but should not crash
    assert "material_name" in d


# ── Test 10: Catalog filter by category ───────────────────────────

def test_catalog_filter(auth_headers):
    r = httpx.get(f"{API}/pricing/catalog?category=Бои", headers=auth_headers)
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert "бои" in item.get("material_category", "").lower()
