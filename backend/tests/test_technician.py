"""
Tests for Technician Mobile View.
Run: pytest backend/tests/test_technician.py -v
"""
import pytest
import httpx
import io
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


# ── Test 1: My sites ──────────────────────────────────────────────

def test_my_sites(auth_headers):
    r = httpx.get(f"{API}/technician/my-sites", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "sites" in d
    assert d["total"] >= 1
    site = d["sites"][0]
    assert "project_id" in site
    assert "name" in site
    assert "has_report_today" in site
    assert "today_hours" in site


# ── Test 2: Site tasks ─────────────────────────────────────────────

def test_site_tasks(auth_headers, project_id):
    r = httpx.get(f"{API}/technician/site/{project_id}/tasks", headers=auth_headers)
    assert r.status_code == 200
    assert "tasks" in r.json()


# ── Test 3: Daily report (creates sessions) ────────────────────────

def test_daily_report(auth_headers, project_id):
    r = httpx.post(f"{API}/technician/daily-report", json={
        "project_id": project_id,
        "entries": [
            {"worker_name": "Иван Тестов", "smr_type": "Довършителни", "hours": 8},
            {"worker_name": "Петър Работник", "smr_type": "Мазилка", "hours": 6},
        ],
        "general_notes": "Нормален работен ден",
    }, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["sessions_created"] == 2
    assert d["total_hours"] == 14
    assert d["report_id"] is not None


# ── Test 4: Daily report with unknown SMR ──────────────────────────

def test_daily_report_unknown_smr(auth_headers, project_id):
    r = httpx.post(f"{API}/technician/daily-report", json={
        "project_id": project_id,
        "entries": [
            {"worker_name": "Тест", "smr_type": "НепознатоСМР_12345", "hours": 3},
        ],
    }, headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["missing_smr_created"]) >= 1


# ── Test 5: Quick SMR ──────────────────────────────────────────────

def test_quick_smr(auth_headers, project_id):
    r = httpx.post(f"{API}/technician/quick-smr", json={
        "project_id": project_id,
        "smr_type": "Спукана тръба",
        "description": "Авария в банята",
        "qty": 1,
        "unit": "бр",
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["missing_smr_id"] is not None


# ── Test 6: Material request ───────────────────────────────────────

def test_material_request(auth_headers, project_id):
    r = httpx.post(f"{API}/technician/material-request", json={
        "project_id": project_id,
        "items": [
            {"item_name": "Цимент", "qty": 10, "unit": "торби"},
            {"item_name": "Пясък", "qty": 2, "unit": "м3"},
        ],
        "urgent": True,
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["request_id"] is not None


# ── Test 7: Photo invoice ──────────────────────────────────────────

def test_photo_invoice(auth_headers, project_id):
    # Create a small test image
    img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    r = httpx.post(f"{API}/technician/photo-invoice",
        files={"file": ("invoice.png", img, "image/png")},
        data={"project_id": project_id, "description": "Фактура за гориво", "amount": "150"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["expense_id"] is not None
    assert r.json()["media_id"] is not None


# ── Test 8: Approve pending expense ────────────────────────────────

def test_approve_expense(auth_headers):
    pending = httpx.get(f"{API}/pending-expenses?status=pending_approval", headers=auth_headers).json()["items"]
    assert len(pending) >= 1
    eid = pending[0]["id"]

    r = httpx.put(f"{API}/pending-expenses/{eid}/approve", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


# ── Test 9: Reject pending expense ─────────────────────────────────

def test_reject_expense(auth_headers, project_id):
    # Create another expense to reject
    img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    httpx.post(f"{API}/technician/photo-invoice",
        files={"file": ("rej.png", img, "image/png")},
        data={"project_id": project_id, "description": "За отказ"},
        headers=auth_headers,
    )
    pending = httpx.get(f"{API}/pending-expenses?status=pending_approval", headers=auth_headers).json()["items"]
    if not pending:
        pytest.skip("No pending expenses")
    eid = pending[0]["id"]

    r = httpx.put(f"{API}/pending-expenses/{eid}/reject?reason=Не%20е%20валидна", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


# ── Test 10: My equipment ──────────────────────────────────────────

def test_my_equipment(auth_headers):
    r = httpx.get(f"{API}/technician/my-equipment", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()


# ── Test 11: Request equipment ─────────────────────────────────────

def test_request_equipment(auth_headers, project_id):
    r = httpx.post(f"{API}/technician/request-equipment", json={
        "project_id": project_id,
        "item_description": "Перфоратор Bosch",
        "needed_from": "2026-04-10",
        "notes": "За пробиване на бетон",
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["request_id"] is not None
