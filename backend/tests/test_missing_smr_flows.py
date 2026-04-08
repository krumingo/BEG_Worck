"""
Tests for Missing SMR Two Flows (emergency vs planned).
Run: pytest backend/tests/test_missing_smr_flows.py -v
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


# ── Test 1: Create emergency item ──────────────────────────────────

def test_create_emergency(auth_headers, project_id):
    r = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Спукан тръба ВиК",
        "urgency_type": "emergency",
        "emergency_reason": "Наводнение в банята — наложителен ремонт",
        "qty": 1,
        "unit": "бр",
        "source": "web",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["urgency_type"] == "emergency"
    assert d["emergency_reason"] is not None
    assert d["status"] == "draft"


# ── Test 2: Create planned item ───────────────────────────────────

def test_create_planned(auth_headers, project_id):
    r = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Допълнителен контакт хол",
        "urgency_type": "planned",
        "qty": 2,
        "unit": "бр",
        "source": "web",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["urgency_type"] == "planned"


# ── Test 3: Execute emergency (valid transition) ──────────────────

def test_execute_emergency(auth_headers, project_id):
    # Create and report
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Авариен ремонт покрив",
        "urgency_type": "emergency",
        "qty": 5,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)

    # Execute
    r = httpx.put(f"{API}/missing-smr/{item['id']}/execute", json={
        "executed_date": "2026-04-08",
        "executed_by": "Иван Майсторов",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert r.json()["executed_by"] == "Иван Майсторов"


# ── Test 4: Execute planned (should fail) ──────────────────────────

def test_execute_planned_fails(auth_headers, project_id):
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Нов кабел",
        "urgency_type": "planned",
        "qty": 10,
        "unit": "м",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)

    r = httpx.put(f"{API}/missing-smr/{item['id']}/execute", json={}, headers=auth_headers)
    assert r.status_code == 400  # Only emergency can be executed


# ── Test 5: Request approval for planned ───────────────────────────

def test_request_approval(auth_headers, project_id):
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Нова точка ВиК",
        "urgency_type": "planned",
        "qty": 1,
        "unit": "бр",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)

    r = httpx.post(f"{API}/missing-smr/{item['id']}/request-approval", json={
        "client_name": "Петър Клиентов",
        "client_notes": "Моля потвърдете",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"
    assert r.json()["client_approval"]["status"] == "pending"
    assert r.json()["client_approval"]["client_name"] == "Петър Клиентов"


# ── Test 6: Client approve ─────────────────────────────────────────

def test_client_approve(auth_headers, project_id):
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Допълнително осветление",
        "urgency_type": "planned",
        "qty": 3,
        "unit": "бр",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)
    httpx.post(f"{API}/missing-smr/{item['id']}/request-approval", json={"client_name": "Клиент"}, headers=auth_headers)

    r = httpx.put(f"{API}/missing-smr/{item['id']}/client-approve", json={
        "client_notes": "Одобрявам",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved_by_client"
    assert r.json()["client_approval"]["status"] == "approved"


# ── Test 7: Client reject ──────────────────────────────────────────

def test_client_reject(auth_headers, project_id):
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Нова стена гипсокартон",
        "urgency_type": "planned",
        "qty": 8,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)
    httpx.post(f"{API}/missing-smr/{item['id']}/request-approval", json={"client_name": "Клиент"}, headers=auth_headers)

    r = httpx.put(f"{API}/missing-smr/{item['id']}/client-reject", json={
        "client_notes": "Твърде скъпо",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected_by_client"
    assert r.json()["client_approval"]["status"] == "rejected"


# ── Test 8: AI estimate ────────────────────────────────────────────

def test_ai_estimate(auth_headers, project_id):
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Шпакловка стени",
        "activity_type": "Довършителни",
        "qty": 20,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()

    r = httpx.post(f"{API}/missing-smr/{item['id']}/ai-estimate", headers=auth_headers, timeout=60.0)
    assert r.status_code == 200
    d = r.json()
    assert d["estimated_price"] > 0
    assert "breakdown" in d
    assert d["item"]["ai_estimated_price"] > 0


# ── Test 9: Batch to offer ─────────────────────────────────────────

def test_batch_to_offer(auth_headers, project_id):
    items = []
    for name in ["Мазилка коридор", "Боядисване коридор"]:
        it = httpx.post(f"{API}/missing-smr", json={
            "project_id": project_id,
            "smr_type": name,
            "qty": 15,
            "unit": "m2",
            "source": "web",
        }, headers=auth_headers).json()
        items.append(it["id"])

    r = httpx.post(f"{API}/missing-smr/batch-to-offer", json={
        "ids": items,
        "offer_name": "Batch Test Offer",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["offer_no"].startswith("OFF-")
    assert r.json()["items_count"] == 2


# ── Test 10: Backward compat (old items without urgency_type) ─────

def test_backward_compat(auth_headers, project_id):
    # Old items default to "planned"
    item = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Old style item",
        "qty": 1,
        "unit": "бр",
        "source": "web",
    }, headers=auth_headers).json()
    # Should have urgency_type = "planned" (default)
    assert item.get("urgency_type") == "planned"

    # Old transitions should still work
    httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reported"}, headers=auth_headers)
    r = httpx.put(f"{API}/missing-smr/{item['id']}/status", json={"status": "reviewed"}, headers=auth_headers)
    assert r.status_code == 200


# ── Test 11: Pending approval endpoint ─────────────────────────────

def test_pending_approval(auth_headers):
    r = httpx.get(f"{API}/missing-smr/pending-approval", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()
    # All returned items should have pending approval
    for item in r.json()["items"]:
        assert item.get("client_approval", {}).get("status") == "pending"


# ── Test 12: Filter by urgency_type ────────────────────────────────

def test_filter_urgency(auth_headers):
    r = httpx.get(f"{API}/missing-smr?urgency_type=emergency", headers=auth_headers)
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item.get("urgency_type") == "emergency"
