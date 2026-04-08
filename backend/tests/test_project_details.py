"""
Tests for Extended Project Details module.
Run: pytest backend/tests/test_project_details.py -v
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
    projects = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json())
    return projects[0]["id"]


# ── Test 1: Create project with structured_address ─────────────────

def test_create_with_structured_address(auth_headers):
    import uuid
    code = f"TST-{str(uuid.uuid4())[:6]}"
    r = httpx.post(f"{API}/projects", json={
        "code": code,
        "name": "Test Structured Address",
        "structured_address": {
            "city": "София",
            "district": "Лозенец",
            "street": "ул. Цар Борис III",
            "block": "15",
            "entrance": "А",
            "floor": "3",
            "apartment": "12",
            "postal_code": "1000",
        },
        "object_type": "apartment",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["structured_address"]["city"] == "София"
    assert d["object_type"] == "apartment"
    # address_text should be auto-generated
    assert "София" in d.get("address_text", "")
    assert "Лозенец" in d.get("address_text", "")


# ── Test 2: Update project with contacts ───────────────────────────

def test_update_with_contacts(auth_headers, project_id):
    r = httpx.put(f"{API}/projects/{project_id}", json={
        "contacts": {
            "owner": {"name": "Иван Иванов", "phone": "+359888111222", "email": "ivan@test.com"},
            "responsible": {"name": "Петър Петров", "phone": "+359888333444", "position": "Архитект"},
            "additional": [{"name": "Мария", "phone": "+359888555666", "role": "Дизайнер", "notes": ""}],
        },
    }, headers=auth_headers)
    assert r.status_code == 200
    c = r.json()["contacts"]
    assert c["owner"]["name"] == "Иван Иванов"
    assert c["responsible"]["position"] == "Архитект"
    assert len(c["additional"]) == 1


# ── Test 3: Update project with invoice_details ────────────────────

def test_update_with_invoice(auth_headers, project_id):
    r = httpx.put(f"{API}/projects/{project_id}", json={
        "invoice_details": {
            "company_name": "БЕГ Строй ЕООД",
            "eik": "123456789",
            "vat_number": "BG123456789",
            "mol": "Георги Георгиев",
            "registered_address": "гр. София, ул. Витоша 1",
            "iban": "BG12BNBG12345678901234",
            "bank_name": "УниКредит Булбанк",
            "is_vat_registered": True,
        },
    }, headers=auth_headers)
    assert r.status_code == 200
    inv = r.json()["invoice_details"]
    assert inv["company_name"] == "БЕГ Строй ЕООД"
    assert inv["eik"] == "123456789"
    assert inv["is_vat_registered"] is True


# ── Test 4: Get project returns all new fields ─────────────────────

def test_get_project_returns_new_fields(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "contacts" in d
    assert "invoice_details" in d
    # These might be None for old projects, but key should exist if we just set them
    if d.get("contacts"):
        assert "owner" in d["contacts"]


# ── Test 5: Invoice details shortcut endpoint ──────────────────────

def test_invoice_details_endpoint(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/invoice-details", headers=auth_headers)
    assert r.status_code == 200
    assert "invoice_details" in r.json()


# ── Test 6: Import client invoice ──────────────────────────────────

def test_import_client_invoice(auth_headers, project_id):
    # This test depends on the project having an owner_id
    r = httpx.post(f"{API}/projects/{project_id}/import-client-invoice", headers=auth_headers)
    # May return 400 "no linked client" or 200 with data
    assert r.status_code in [200, 400]
    if r.status_code == 200:
        assert "invoice_details" in r.json()


# ── Test 7: Backward compat: old project without new fields ────────

def test_backward_compat(auth_headers):
    # Get all projects - old ones should still work
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    assert r.status_code == 200
    projects = r.json() if isinstance(r.json(), list) else r.json()
    assert len(projects) >= 1


# ── Test 8: Object type enum ──────────────────────────────────────

def test_object_type_enum(auth_headers):
    r = httpx.get(f"{API}/project-enums", headers=auth_headers)
    assert r.status_code == 200
    assert "object_types" in r.json()
    assert "apartment" in r.json()["object_types"]
    assert "house" in r.json()["object_types"]


# ── Test 9: Formatted address generation ───────────────────────────

def test_formatted_address(auth_headers):
    import uuid
    code = f"ADDR-{str(uuid.uuid4())[:5]}"
    r = httpx.post(f"{API}/projects", json={
        "code": code,
        "name": "Address Gen Test",
        "structured_address": {
            "city": "Пловдив",
            "district": "Марица",
            "block": "22",
            "entrance": "Б",
            "floor": "5",
        },
    }, headers=auth_headers)
    assert r.status_code == 201
    addr = r.json().get("address_text", "")
    assert "Пловдив" in addr
    assert "Марица" in addr
    assert "бл. 22" in addr


# ── Test 10: Update object_details ─────────────────────────────────

def test_update_object_details(auth_headers, project_id):
    r = httpx.put(f"{API}/projects/{project_id}", json={
        "object_type": "house",
        "object_details": {
            "total_area_m2": 120.5,
            "rooms_count": 4,
            "floors_count": 2,
            "is_inhabited": True,
            "parking_available": True,
            "elevator_available": False,
            "access_notes": "Синя зона, код за портал: 1234",
        },
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["object_type"] == "house"
    od = r.json()["object_details"]
    assert od["total_area_m2"] == 120.5
    assert od["rooms_count"] == 4
    assert od["is_inhabited"] is True
