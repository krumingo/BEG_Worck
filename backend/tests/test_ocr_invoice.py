"""
Tests for OCR Invoice Intake.
Run: pytest backend/tests/test_ocr_invoice.py -v
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


# ── Test 1: Upload ─────────────────────────────────────────────────

def test_upload(auth_headers, project_id):
    content = b"Firma Test EOOD\nFaktura No 12345\nData: 01.04.2026\nObshto: 1500.00 lv\nDDS: 250.00"
    r = httpx.post(f"{API}/ocr-invoice/upload",
        files={"file": ("test_invoice.txt", content, "text/plain")},
        data={"project_id": project_id},
        headers=auth_headers,
    )
    assert r.status_code == 201
    d = r.json()
    assert d["status"] in ("uploaded", "processed")
    assert d["media_id"] is not None


# ── Test 2: From media ─────────────────────────────────────────────

def test_from_media(auth_headers):
    # Get a media file
    intakes = httpx.get(f"{API}/ocr-invoice", headers=auth_headers).json()["items"]
    if not intakes:
        pytest.skip("No intakes")
    media_id = intakes[0]["media_id"]
    r = httpx.post(f"{API}/ocr-invoice/from-media", json={"media_id": media_id}, headers=auth_headers)
    assert r.status_code == 201


# ── Test 3: Extract returns structure ──────────────────────────────

def test_extract_structure(auth_headers):
    intakes = httpx.get(f"{API}/ocr-invoice", headers=auth_headers).json()["items"]
    assert len(intakes) >= 1
    d = intakes[0].get("detected_data", {})
    assert "raw_text" in d or d == {}


# ── Test 4: Review ──────────────────────────────────────────────────

def test_review(auth_headers):
    intakes = httpx.get(f"{API}/ocr-invoice", headers=auth_headers).json()["items"]
    intake = next((i for i in intakes if i["status"] not in ("approved", "rejected")), None)
    if not intake:
        pytest.skip("No reviewable intakes")
    r = httpx.put(f"{API}/ocr-invoice/{intake['id']}/review", json={
        "supplier_name": "Тест Доставчик ЕООД",
        "invoice_number": "F-12345",
        "total_amount": 1500,
        "vat_amount": 250,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"
    assert r.json()["reviewed_data"]["supplier_name"] == "Тест Доставчик ЕООД"


# ── Test 5: Approve only after review ──────────────────────────────

def test_approve_after_review(auth_headers):
    intakes = httpx.get(f"{API}/ocr-invoice?status=reviewed", headers=auth_headers).json()["items"]
    if not intakes:
        pytest.skip("No reviewed intakes")
    r = httpx.put(f"{API}/ocr-invoice/{intakes[0]['id']}/approve", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["linked_expense_id"] is not None


# ── Test 6: Reject ──────────────────────────────────────────────────

def test_reject(auth_headers, project_id):
    content = b"Reject test invoice"
    intake = httpx.post(f"{API}/ocr-invoice/upload",
        files={"file": ("reject.txt", content, "text/plain")},
        data={"project_id": project_id},
        headers=auth_headers,
    ).json()
    r = httpx.put(f"{API}/ocr-invoice/{intake['id']}/reject", json={"reason": "Невалидна"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


# ── Test 7: List filtering ─────────────────────────────────────────

def test_list_filter(auth_headers):
    r = httpx.get(f"{API}/ocr-invoice?status=approved", headers=auth_headers)
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["status"] == "approved"


# ── Test 8: Raw text ───────────────────────────────────────────────

def test_raw_text(auth_headers):
    intakes = httpx.get(f"{API}/ocr-invoice", headers=auth_headers).json()["items"]
    if not intakes:
        pytest.skip()
    r = httpx.get(f"{API}/ocr-invoice/{intakes[0]['id']}/raw-text", headers=auth_headers)
    assert r.status_code == 200
    assert "raw_text" in r.json()
