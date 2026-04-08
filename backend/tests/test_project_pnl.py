"""
Tests for Project P&L module.
Run: pytest backend/tests/test_project_pnl.py -v
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


# ── Test 1: Full P&L ──────────────────────────────────────────────

def test_full_pnl(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "budget" in d
    assert "revenue" in d
    assert "expense" in d
    assert "profit" in d
    assert d["profit"]["status"] in ["profitable", "break_even", "loss"]


# ── Test 2: P&L Summary ───────────────────────────────────────────

def test_pnl_summary(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl/summary", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "total_budget" in d
    assert "total_revenue" in d
    assert "total_expense" in d
    assert "gross_profit" in d
    assert "margin_pct" in d


# ── Test 3: P&L Breakdown ─────────────────────────────────────────

def test_pnl_breakdown(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl/breakdown", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "expense" in d
    assert "labor_cost" in d["expense"]
    assert "material_cost" in d["expense"]
    assert "subcontractor_cost" in d["expense"]


# ── Test 4: P&L with work_sessions (labor cost) ───────────────────

def test_pnl_labor(auth_headers, project_id):
    # Work sessions exist from previous tests
    r = httpx.get(f"{API}/projects/{project_id}/pnl", headers=auth_headers)
    assert r.status_code == 200
    # labor_cost should be >= 0
    assert r.json()["expense"]["labor_cost"] >= 0
    assert r.json()["expense"]["labor_hours"] >= 0


# ── Test 5: P&L with invoices (revenue) ───────────────────────────

def test_pnl_revenue(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl", headers=auth_headers)
    assert r.status_code == 200
    # Revenue structure should be correct
    rev = r.json()["revenue"]
    assert "invoiced_total" in rev
    assert "paid_total" in rev
    assert "total_revenue" in rev


# ── Test 6: P&L with contract payments ─────────────────────────────

def test_pnl_contracts(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl", headers=auth_headers)
    assert r.status_code == 200
    assert "contract_cost" in r.json()["expense"]
    # Contract payments exist from previous weekly payroll tests
    assert r.json()["expense"]["contract_cost"] >= 0


# ── Test 7: P&L Trend ─────────────────────────────────────────────

def test_pnl_trend(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl/trend?months=3", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "months" in d
    assert len(d["months"]) == 3
    for m in d["months"]:
        assert "month" in m
        assert "revenue" in m
        assert "expense" in m
        assert "profit" in m


# ── Test 8: Org P&L Overview ──────────────────────────────────────

def test_org_overview(auth_headers):
    r = httpx.get(f"{API}/org/pnl-overview", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "projects" in d
    assert "totals" in d
    assert len(d["projects"]) >= 1
    for p in d["projects"]:
        assert "budget" in p
        assert "revenue" in p
        assert "expense" in p
        assert "profit" in p
        assert "margin_pct" in p
        assert "status" in p


# ── Test 9: Profit calculation correctness ─────────────────────────

def test_profit_calc(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/pnl", headers=auth_headers)
    d = r.json()
    # Verify: gross_profit = total_revenue - total_expense
    expected = round(d["revenue"]["total_revenue"] - d["expense"]["total_expense"], 2)
    assert abs(d["profit"]["gross_profit"] - expected) < 0.02


# ── Test 10: Empty project P&L ─────────────────────────────────────

def test_empty_pnl(auth_headers):
    import uuid
    code = f"PNL-{str(uuid.uuid4())[:5]}"
    p = httpx.post(f"{API}/projects", json={
        "code": code, "name": "Empty PNL Test",
    }, headers=auth_headers).json()

    r = httpx.get(f"{API}/projects/{p['id']}/pnl", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["expense"]["total_expense"] == 0
    assert d["revenue"]["total_revenue"] == 0
    assert d["profit"]["gross_profit"] == 0
    assert d["profit"]["status"] == "break_even"
