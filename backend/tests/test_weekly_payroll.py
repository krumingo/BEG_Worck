"""
Tests for Weekly Payroll + Contract Payments module.
Run: pytest backend/tests/test_weekly_payroll.py -v
"""
import pytest
import httpx
from pathlib import Path
from datetime import datetime, timezone, timedelta

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


# ── Test 1: Create weekly run ──────────────────────────────────────

def test_create_weekly_run(auth_headers):
    now = datetime.now(timezone.utc)
    mon = now - timedelta(days=now.weekday())
    sun = mon + timedelta(days=6)
    r = httpx.post(f"{API}/payroll/weekly-run", json={
        "week_start": mon.strftime("%Y-%m-%d"),
        "week_end": sun.strftime("%Y-%m-%d"),
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["period_type"] == "weekly"
    assert d["source"] == "work_sessions"
    assert d["status"] == "Draft"


# ── Test 2: Generate weekly payslips from work_sessions ────────────

def test_generate_weekly_payslips(auth_headers, project_id):
    now = datetime.now(timezone.utc)
    mon = now - timedelta(days=now.weekday())
    sun = mon + timedelta(days=6)

    # Create a work session for this week
    httpx.post(f"{API}/work-sessions/start", json={"site_id": project_id}, headers=auth_headers)
    httpx.post(f"{API}/work-sessions/end", json={}, headers=auth_headers)

    # Create weekly run
    run = httpx.post(f"{API}/payroll/weekly-run", json={
        "week_start": mon.strftime("%Y-%m-%d"),
        "week_end": sun.strftime("%Y-%m-%d"),
        "name": "Test Weekly Gen",
    }, headers=auth_headers).json()
    run_id = run["id"]

    # Generate
    r = httpx.post(f"{API}/payroll/{run_id}/generate-weekly", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["workers"] >= 1


# ── Test 3: Weekly payslip has overtime breakdown ──────────────────

def test_weekly_payslip_breakdown(auth_headers):
    # Get the latest weekly run
    runs = httpx.get(f"{API}/payroll-runs?status=Draft", headers=auth_headers).json()
    weekly_runs = [r for r in runs if r.get("period_type") == "weekly"]
    assert len(weekly_runs) >= 1
    
    run_id = weekly_runs[0]["id"]
    detail = httpx.get(f"{API}/payroll-runs/{run_id}", headers=auth_headers).json()
    payslips = detail.get("payslips", [])
    assert len(payslips) >= 1
    
    ps = payslips[0]
    assert "regular_hours" in ps or "base_amount" in ps
    assert "overtime_breakdown" in ps or "overtime_amount" in ps


# ── Test 4: My weekly summary ─────────────────────────────────────

def test_my_weekly_summary(auth_headers):
    r = httpx.get(f"{API}/payroll/my-weekly-summary", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "regular_hours" in d
    assert "overtime_hours" in d
    assert "gross" in d
    assert "net" in d
    assert "sessions_count" in d


# ── Test 5: Create contract payment with tranches ──────────────────

def test_create_contract_payment(auth_headers, project_id):
    r = httpx.post(f"{API}/contract-payments", json={
        "worker_name": "Бригада Иванов",
        "description": "Шпакловка етаж 3",
        "total_amount": 5000,
        "site_id": project_id,
        "contract_type": "milestone",
        "tranches": [
            {"amount": 2000, "due_date": "2026-04-15"},
            {"amount": 2000, "due_date": "2026-04-22"},
            {"amount": 1000, "due_date": "2026-04-30"},
        ],
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["worker_name"] == "Бригада Иванов"
    assert d["total_amount"] == 5000
    assert len(d["tranches"]) == 3
    assert d["status"] == "active"


# ── Test 6: Pay tranche + auto-complete ────────────────────────────

def test_pay_tranche_auto_complete(auth_headers, project_id):
    # Create one-time payment
    cp = httpx.post(f"{API}/contract-payments", json={
        "worker_name": "Тест Работник",
        "total_amount": 500,
        "site_id": project_id,
    }, headers=auth_headers).json()
    cp_id = cp["id"]
    assert len(cp["tranches"]) == 1

    # Pay the single tranche
    r = httpx.post(f"{API}/contract-payments/{cp_id}/pay-tranche", json={
        "tranche_index": 0,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["tranches"][0]["status"] == "paid"
    assert r.json()["status"] == "completed"  # auto-completed


# ── Test 7: List contract payments ─────────────────────────────────

def test_list_contract_payments(auth_headers):
    r = httpx.get(f"{API}/contract-payments", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 2


# ── Test 8: Cannot delete with paid tranches ───────────────────────

def test_cannot_delete_paid(auth_headers):
    # Find one with paid tranches
    items = httpx.get(f"{API}/contract-payments?status=completed", headers=auth_headers).json()["items"]
    if items:
        r = httpx.delete(f"{API}/contract-payments/{items[0]['id']}", headers=auth_headers)
        assert r.status_code == 400  # has paid tranches


# ── Test 9: Delete pending contract ────────────────────────────────

def test_delete_pending(auth_headers, project_id):
    cp = httpx.post(f"{API}/contract-payments", json={
        "worker_name": "Delete Test",
        "total_amount": 100,
    }, headers=auth_headers).json()
    r = httpx.delete(f"{API}/contract-payments/{cp['id']}", headers=auth_headers)
    assert r.status_code == 200


# ── Test 10: Get contract detail ───────────────────────────────────

def test_get_contract_detail(auth_headers):
    items = httpx.get(f"{API}/contract-payments", headers=auth_headers).json()["items"]
    assert len(items) >= 1
    r = httpx.get(f"{API}/contract-payments/{items[0]['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert "tranches" in r.json()
