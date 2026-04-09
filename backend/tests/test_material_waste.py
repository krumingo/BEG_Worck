"""
Tests for Material Waste Tracking.
Run: pytest backend/tests/test_material_waste.py -v
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


# ── Test 1: Empty project waste summary ────────────────────────────

def test_empty_waste(auth_headers):
    import uuid
    code = f"WS-{str(uuid.uuid4())[:5]}"
    p = httpx.post(f"{API}/projects", json={"code": code, "name": "Waste Empty"}, headers=auth_headers).json()
    r = httpx.get(f"{API}/projects/{p['id']}/material-waste", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["summary"]["materials_count"] == 0
    assert r.json()["summary"]["total_waste_items"] == 0


# ── Test 2: Create waste entry ─────────────────────────────────────

def test_create_waste(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/material-waste", json={
        "material_name": "Цимент",
        "qty": 5,
        "unit": "торби",
        "waste_type": "damaged",
        "notes": "Намокрен при дъжд",
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["material_name"] == "Цимент"
    assert r.json()["waste_type"] == "damaged"


# ── Test 3: Waste log listing ──────────────────────────────────────

def test_waste_log(auth_headers, project_id):
    # Add another entry
    httpx.post(f"{API}/projects/{project_id}/material-waste", json={
        "material_name": "Пясък",
        "qty": 0.5,
        "unit": "м3",
        "waste_type": "lost",
    }, headers=auth_headers)

    r = httpx.get(f"{API}/projects/{project_id}/material-waste/log", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 2


# ── Test 4: Summary with waste entries ─────────────────────────────

def test_summary_with_waste(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/material-waste", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["total_waste_items"] >= 2
    assert d["summary"]["total_waste_qty"] > 0


# ── Test 5: Material entry fields ──────────────────────────────────

def test_material_fields(auth_headers, project_id):
    d = httpx.get(f"{API}/projects/{project_id}/material-waste", headers=auth_headers).json()
    for m in d["materials"]:
        assert "material_name" in m
        assert "planned_qty" in m
        assert "issued_qty" in m
        assert "wasted_qty" in m
        assert "variance_vs_planned" in m
        assert "status" in m
        assert m["status"] in ["ok", "warning", "overuse"]


# ── Test 6: Status logic ──────────────────────────────────────────

def test_status_logic():
    from app.services.material_waste import _status
    assert _status(50, 100) == "ok"
    assert _status(100, 100) == "ok"
    assert _status(105, 100) == "warning"
    assert _status(111, 100) == "overuse"
    assert _status(10, 0) == "ok"  # no planned = ok


# ── Test 7: Compact endpoint ──────────────────────────────────────

def test_compact(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/material-waste/compact", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "summary" in d
    assert "top_overuse" in d
    assert "top_waste" in d
    assert len(d["top_overuse"]) <= 5


# ── Test 8: Different waste types ──────────────────────────────────

def test_waste_types(auth_headers, project_id):
    for wt in ["broken", "unused", "returnable"]:
        r = httpx.post(f"{API}/projects/{project_id}/material-waste", json={
            "material_name": f"Тест {wt}",
            "qty": 1,
            "waste_type": wt,
        }, headers=auth_headers)
        assert r.status_code == 201
        assert r.json()["waste_type"] == wt
