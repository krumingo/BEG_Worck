"""
Tests for SMR Analysis module.
Run: pytest backend/tests/test_smr_analysis.py -v
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


@pytest.fixture(scope="module")
def analysis_id(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Test Analysis Alpha",
    }, headers=auth_headers)
    assert r.status_code == 201
    return r.json()["id"]


# ── Test 1: Create analysis ───────────────────────────────────────

def test_create_analysis(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Test Create",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "Test Create"
    assert d["status"] == "draft"
    assert d["version"] >= 1
    assert d["totals"]["grand_total"] == 0


# ── Test 2: List analyses ─────────────────────────────────────────

def test_list_analyses(auth_headers, project_id, analysis_id):
    r = httpx.get(f"{API}/smr-analyses?project_id={project_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


# ── Test 3: Add line ──────────────────────────────────────────────

def test_add_line(auth_headers, analysis_id):
    r = httpx.post(f"{API}/smr-analyses/{analysis_id}/lines", json={
        "smr_type": "Шпакловка стени",
        "unit": "m2",
        "qty": 50,
        "labor_price_per_unit": 12.0,
        "logistics_pct": 10,
        "markup_pct": 15,
        "risk_pct": 5,
        "materials": [
            {"name": "Гипсова шпакловка", "unit": "кг", "qty_per_unit": 1.5, "unit_price": 2.0, "waste_pct": 5},
            {"name": "Грунд", "unit": "л", "qty_per_unit": 0.15, "unit_price": 3.0, "waste_pct": 3},
        ],
    }, headers=auth_headers)
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert len(lines) >= 1
    ln = lines[-1]
    assert ln["smr_type"] == "Шпакловка стени"
    assert ln["material_cost_per_unit"] > 0
    assert ln["final_price_per_unit"] > 0
    assert ln["final_total"] > 0


# ── Test 4: Update line (change qty) ──────────────────────────────

def test_update_line(auth_headers, analysis_id):
    doc = httpx.get(f"{API}/smr-analyses/{analysis_id}", headers=auth_headers).json()
    line_id = doc["lines"][0]["line_id"]
    old_total = doc["lines"][0]["final_total"]

    r = httpx.put(f"{API}/smr-analyses/{analysis_id}/lines/{line_id}", json={
        "qty": 100,
    }, headers=auth_headers)
    assert r.status_code == 200
    new_total = r.json()["lines"][0]["final_total"]
    assert new_total > old_total  # doubled qty → higher total


# ── Test 5: Recalculate endpoint ──────────────────────────────────

def test_recalculate(auth_headers, analysis_id):
    r = httpx.post(f"{API}/smr-analyses/{analysis_id}/recalculate", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["totals"]["grand_total"] > 0


# ── Test 6: AI suggest ────────────────────────────────────────────

def test_ai_suggest(auth_headers, analysis_id):
    doc = httpx.get(f"{API}/smr-analyses/{analysis_id}", headers=auth_headers).json()
    line_id = doc["lines"][0]["line_id"]

    r = httpx.post(f"{API}/smr-analyses/{analysis_id}/ai-suggest", json={
        "line_id": line_id,
    }, headers=auth_headers, timeout=60.0)
    assert r.status_code == 200
    assert "proposal" in r.json()
    assert "analysis" in r.json()
    # AI should have populated materials
    updated_line = r.json()["analysis"]["lines"][0]
    assert updated_line["labor_price_per_unit"] > 0


# ── Test 7: Approve flow ──────────────────────────────────────────

def test_approve(auth_headers, project_id):
    # Create fresh analysis for approve test (independent from AI suggest)
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Approve Test",
    }, headers=auth_headers)
    aid = r.json()["id"]
    r = httpx.post(f"{API}/smr-analyses/{aid}/approve", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["approved_by"] is not None


# ── Test 8: Lock flow ─────────────────────────────────────────────

def test_lock(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Lock Test",
    }, headers=auth_headers)
    aid = r.json()["id"]
    r = httpx.post(f"{API}/smr-analyses/{aid}/lock", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "locked"


# ── Test 9: Locked analysis cannot add line ────────────────────────

def test_locked_cannot_add_line(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Lock Block Test",
    }, headers=auth_headers)
    aid = r.json()["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lock", headers=auth_headers)
    r = httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Test",
        "unit": "m2",
        "qty": 1,
    }, headers=auth_headers)
    assert r.status_code == 400


# ── Test 10: Snapshot + compare versions ───────────────────────────

def test_snapshot_and_compare(auth_headers, project_id):
    # Create a fresh analysis for snapshot test
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Snapshot Test",
    }, headers=auth_headers)
    aid = r.json()["id"]
    v1 = r.json()["version"]

    # Add a line
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Боядисване",
        "unit": "m2",
        "qty": 20,
        "labor_price_per_unit": 6,
    }, headers=auth_headers)

    # Snapshot
    snap = httpx.post(f"{API}/smr-analyses/{aid}/snapshot", headers=auth_headers)
    assert snap.status_code == 200
    v2 = snap.json()["version"]
    assert v2 > v1
    snap_id = snap.json()["id"]

    # Compare
    cmp = httpx.get(f"{API}/smr-analyses/{snap_id}/compare/{v1}", headers=auth_headers)
    assert cmp.status_code == 200
    assert "current" in cmp.json()
    assert "compare" in cmp.json()
    assert "diff" in cmp.json()


# ── Test 11: To-offer bridge ──────────────────────────────────────

def test_to_offer(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Offer Bridge Test",
    }, headers=auth_headers)
    aid = r.json()["id"]

    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Мазилка",
        "unit": "m2",
        "qty": 30,
        "labor_price_per_unit": 12,
        "materials": [{"name": "Мазилка", "unit": "кг", "qty_per_unit": 1.2, "unit_price": 3.0, "waste_pct": 5}],
    }, headers=auth_headers)

    offer = httpx.post(f"{API}/smr-analyses/{aid}/to-offer", headers=auth_headers)
    assert offer.status_code == 200
    assert offer.json()["ok"] is True
    assert offer.json()["offer_no"].startswith("OFF-")


# ── Test 12: Delete line ──────────────────────────────────────────

def test_delete_line(auth_headers, project_id):
    r = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id,
        "name": "Delete Line Test",
    }, headers=auth_headers)
    aid = r.json()["id"]

    add = httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Test Line",
        "unit": "m2",
        "qty": 10,
    }, headers=auth_headers)
    line_id = add.json()["lines"][0]["line_id"]

    d = httpx.delete(f"{API}/smr-analyses/{aid}/lines/{line_id}", headers=auth_headers)
    assert d.status_code == 200
    assert len(d.json()["lines"]) == 0
