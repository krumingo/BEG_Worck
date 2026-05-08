"""
Tests for Client Summary endpoints.
Run: pytest backend/tests/test_client_summary.py -v
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
def client_id(auth_headers):
    # Create a test client
    r = httpx.post(f"{API}/clients", json={
        "type": "company",
        "companyName": "Тест Клиент ЕООД",
        "eik": "999888777",
        "phone": "+359888999000",
        "email": "test@client.bg",
    }, headers=auth_headers)
    if r.status_code == 201:
        return r.json()["id"]
    # Find existing
    clients = httpx.get(f"{API}/clients", headers=auth_headers).json()
    items = clients.get("items", clients) if isinstance(clients, dict) else clients
    return items[0]["id"] if items else None


# ── Test 1: Client summary with projects ───────────────────────────

def test_client_summary(auth_headers, client_id):
    r = httpx.get(f"{API}/clients/{client_id}/summary", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "client" in d
    assert "projects" in d
    assert "totals" in d
    assert "invoices" in d
    assert "projects_count" in d["totals"]
    assert "total_revenue" in d["totals"]
    assert "total_paid" in d["totals"]
    assert "total_outstanding" in d["totals"]


# ── Test 2: Client summary with invoices ───────────────────────────

def test_client_summary_structure(auth_headers, client_id):
    r = httpx.get(f"{API}/clients/{client_id}/summary", headers=auth_headers)
    d = r.json()
    assert isinstance(d["invoices"], list)
    for inv in d["invoices"]:
        assert "invoice_no" in inv or "id" in inv


# ── Test 3: Client with no projects (empty) ───────────────────────

def test_client_no_projects(auth_headers):
    # Create a brand new client with no projects
    c = httpx.post(f"{API}/clients", json={
        "type": "person",
        "name": "Нов Празен Клиент",
        "fullName": "Нов Празен Клиент",
        "phone": "+359111222333",
    }, headers=auth_headers)
    if c.status_code != 201:
        pytest.skip(f"Could not create client: {c.text}")
    cid = c.json()["id"]

    r = httpx.get(f"{API}/clients/{cid}/summary", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["totals"]["projects_count"] == 0
    assert d["totals"]["total_revenue"] == 0
    assert len(d["projects"]) == 0


# ── Test 4: Client projects endpoint ───────────────────────────────

def test_client_projects(auth_headers, client_id):
    r = httpx.get(f"{API}/clients/{client_id}/projects", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()
    assert "total" in r.json()


# ── Test 5: Client invoices endpoint ───────────────────────────────

def test_client_invoices(auth_headers, client_id):
    r = httpx.get(f"{API}/clients/{client_id}/invoices", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()
    assert "total" in r.json()


# ── Test 6: Backward compat — project without client_id ────────────

def test_backward_compat(auth_headers):
    # Get a project that may not have owner_id
    projects = httpx.get(f"{API}/projects", headers=auth_headers).json()
    items = projects if isinstance(projects, list) else projects.get("items", projects)
    assert len(items) >= 1
    # Projects list works (backward compat)
    assert items[0].get("id") is not None
