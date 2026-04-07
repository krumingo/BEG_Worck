"""
Tests for Missing SMR module.
Run: pytest backend/tests/test_missing_smr.py -v
"""
import pytest
import httpx
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from frontend .env
    fe_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
    if fe_env.exists():
        for line in fe_env.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"

# Test credentials
EMAIL = "admin@begwork.com"
PASSWORD = "AdminTest123!Secure"


@pytest.fixture(scope="module")
def auth_headers():
    """Login and return auth headers."""
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    """Get an existing project ID."""
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    assert r.status_code == 200
    projects = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    assert len(projects) > 0, "No projects found, create one first"
    return projects[0]["id"]


@pytest.fixture(scope="module")
def created_item_id(auth_headers, project_id):
    """Create a missing SMR item for testing and return its ID."""
    r = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Шпакловка стени",
        "activity_type": "Довършителни",
        "activity_subtype": "Шпакловка",
        "floor": "2",
        "room": "Хол",
        "zone": "Стена А",
        "qty": 25.5,
        "unit": "m2",
        "labor_hours_est": 4.0,
        "material_notes": "Ротбанд 30кг x2",
        "notes": "Открито при оглед на 15.02",
        "source": "web",
    }, headers=auth_headers)
    assert r.status_code == 201, f"Create failed: {r.text}"
    return r.json()["id"]


# ── Test 1: Create Missing SMR ────────────────────────────────────

def test_create_missing_smr(auth_headers, project_id):
    r = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Боядисване таван",
        "activity_type": "Боядисване",
        "floor": "3",
        "room": "Спалня",
        "qty": 18,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert data["smr_type"] == "Боядисване таван"
    assert data["status"] == "draft"
    assert data["qty"] == 18
    assert data["project_id"] == project_id
    # Cleanup
    httpx.delete(f"{API}/missing-smr/{data['id']}", headers=auth_headers)


# ── Test 2: List with filters ─────────────────────────────────────

def test_list_missing_smr(auth_headers, created_item_id, project_id):
    r = httpx.get(f"{API}/missing-smr?project_id={project_id}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["total"] >= 1
    ids = [i["id"] for i in data["items"]]
    assert created_item_id in ids


def test_list_filter_by_status(auth_headers, created_item_id):
    r = httpx.get(f"{API}/missing-smr?status=draft", headers=auth_headers)
    assert r.status_code == 200
    assert all(i["status"] == "draft" for i in r.json()["items"])


def test_list_filter_by_floor(auth_headers, created_item_id):
    r = httpx.get(f"{API}/missing-smr?floor=2", headers=auth_headers)
    assert r.status_code == 200
    assert all(i["floor"] == "2" for i in r.json()["items"])


# ── Test 3: Get single item ───────────────────────────────────────

def test_get_missing_smr(auth_headers, created_item_id):
    r = httpx.get(f"{API}/missing-smr/{created_item_id}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == created_item_id
    assert data["smr_type"] == "Шпакловка стени"
    assert data["floor"] == "2"
    assert data["room"] == "Хол"


# ── Test 4: Update item ───────────────────────────────────────────

def test_update_missing_smr(auth_headers, created_item_id):
    r = httpx.put(f"{API}/missing-smr/{created_item_id}", json={
        "qty": 30,
        "notes": "Коригирана площ",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["qty"] == 30
    assert r.json()["notes"] == "Коригирана площ"


# ── Test 5: Status transitions ────────────────────────────────────

def test_status_draft_to_reported(auth_headers, created_item_id):
    r = httpx.put(f"{API}/missing-smr/{created_item_id}/status", json={"status": "reported"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "reported"


def test_status_reported_to_reviewed(auth_headers, created_item_id):
    r = httpx.put(f"{API}/missing-smr/{created_item_id}/status", json={"status": "reviewed"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"


# ── Test 6: Invalid status transition ─────────────────────────────

def test_invalid_status_transition(auth_headers, created_item_id):
    # Currently "reviewed" - cannot go back to "draft"
    r = httpx.put(f"{API}/missing-smr/{created_item_id}/status", json={"status": "draft"}, headers=auth_headers)
    assert r.status_code == 400


# ── Test 7: Bridge to Analysis ────────────────────────────────────

def test_bridge_to_analysis(auth_headers, created_item_id):
    r = httpx.post(f"{API}/missing-smr/{created_item_id}/to-analysis", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["extra_work_draft_id"] is not None
    assert data["missing_smr"]["status"] == "analyzed"
    assert data["missing_smr"]["linked_extra_work_id"] == data["extra_work_draft_id"]


# ── Test 8: Bridge to Offer ───────────────────────────────────────

def test_bridge_to_offer(auth_headers, created_item_id):
    r = httpx.post(f"{API}/missing-smr/{created_item_id}/to-offer", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["offer_id"] is not None
    assert data["offer_no"].startswith("OFF-")
    assert data["missing_smr"]["status"] == "offered"
    assert data["missing_smr"]["linked_offer_id"] == data["offer_id"]


# ── Test 9: Cannot delete non-draft ───────────────────────────────

def test_cannot_delete_non_draft(auth_headers, created_item_id):
    r = httpx.delete(f"{API}/missing-smr/{created_item_id}", headers=auth_headers)
    assert r.status_code == 400  # Item is now "offered", not "draft"


# ── Test 10: 404 for non-existent item ────────────────────────────

def test_not_found(auth_headers):
    r = httpx.get(f"{API}/missing-smr/nonexistent-id-123", headers=auth_headers)
    assert r.status_code == 404
